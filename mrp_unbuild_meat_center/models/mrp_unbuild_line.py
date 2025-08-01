# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Developer: Almus Dev (JDV-ALM) - www.almus.dev

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare, float_round


class MrpUnbuildLine(models.Model):
    """Líneas editables para orden de desmantelamiento"""
    _name = 'mrp.unbuild.line'
    _description = 'Línea de Desmantelamiento'
    _order = 'sequence, id'
    
    unbuild_id = fields.Many2one(
        'mrp.unbuild', 
        string='Orden de Desmantelamiento',
        required=True, 
        ondelete='cascade',
        index=True
    )
    sequence = fields.Integer(
        string='Secuencia', 
        default=10
    )
    product_id = fields.Many2one(
        'product.product', 
        string='Producto',
        required=True,
        check_company=True
    )
    product_tracking = fields.Selection(
        related='product_id.tracking',
        string='Seguimiento'
    )
    expected_qty = fields.Float(
        string='Cantidad Esperada',
        digits='Product Unit of Measure',
        readonly=True,
        help="Cantidad según la lista de materiales"
    )
    actual_qty = fields.Float(
        string='Cantidad Real',
        digits='Product Unit of Measure',
        required=True,
        help="Cantidad real obtenida del desmantelamiento"
    )
    product_uom_id = fields.Many2one(
        'uom.uom', 
        string='Unidad de Medida',
        required=True
    )
    product_uom_category_id = fields.Many2one(
        related='product_id.uom_id.category_id',
        string='Categoría UdM'
    )
    is_waste = fields.Boolean(
        string='Es Desecho',
        default=False,
        help="Marcar si este producto es desecho/merma sin valor"
    )
    
    # Factor de valor desde la BoM
    value_factor = fields.Float(
        string='Factor de Valor',
        default=1.0,
        digits=(12, 2),
        help="Factor multiplicador para distribución de costos heredado de la BoM"
    )
    
    # Distribución de costo calculada
    cost_share = fields.Float(
        string='Distribución de Costo (%)',
        digits=(5, 2),
        compute='_compute_cost_share',
        store=True,
        help="Porcentaje del costo total asignado a este producto"
    )
    
    # Campo para permitir ajuste manual
    cost_share_manual = fields.Float(
        string='Ajuste Manual de Costo (%)',
        digits=(5, 2),
        help="Dejar vacío para cálculo automático. "
             "Ingresar valor para distribución manual del costo."
    )
    
    use_manual_cost = fields.Boolean(
        string='Usar Costo Manual',
        default=False,
        help="Activar para usar distribución manual de costos"
    )
    
    lot_id = fields.Many2one(
        'stock.lot', 
        string='Lote/Número de Serie',
        domain="[('product_id', '=', product_id), ('company_id', '=', company_id)]",
        check_company=True
    )
    company_id = fields.Many2one(
        related='unbuild_id.company_id',
        string='Compañía',
        store=True
    )
    
    # Campo para mostrar valor relativo
    relative_value = fields.Float(
        string='Valor Relativo',
        compute='_compute_relative_value',
        help="Valor relativo considerando cantidad y factor"
    )
    
    @api.depends('actual_qty', 'value_factor', 'is_waste', 
                 'unbuild_id.unbuild_line_ids.actual_qty', 
                 'unbuild_id.unbuild_line_ids.value_factor',
                 'unbuild_id.unbuild_line_ids.is_waste',
                 'use_manual_cost', 'cost_share_manual')
    def _compute_cost_share(self):
        """Calcula la distribución del costo considerando el factor de valor"""
        for line in self:
            if line.use_manual_cost and line.cost_share_manual > 0:
                # Usar valor manual si está activado
                line.cost_share = line.cost_share_manual / 100.0  # Convertir a decimal
            elif line.is_waste:
                line.cost_share = 0.0
            else:
                # Calcular basado en cantidad × factor de valor
                good_lines = line.unbuild_id.unbuild_line_ids.filtered(lambda l: not l.is_waste)
                
                # Calcular suma ponderada total (cantidad × factor)
                total_weighted_value = sum(
                    l._get_qty_in_base_uom() * l.value_factor 
                    for l in good_lines
                )
                
                if total_weighted_value > 0:
                    line_weighted_value = line._get_qty_in_base_uom() * line.value_factor
                    line.cost_share = line_weighted_value / total_weighted_value
                else:
                    line.cost_share = 0.0
    
    @api.depends('actual_qty', 'value_factor')
    def _compute_relative_value(self):
        """Calcula el valor relativo del producto"""
        for line in self:
            line.relative_value = line.actual_qty * line.value_factor
    
    def _get_qty_in_base_uom(self):
        """Convierte la cantidad a la UdM base del producto para cálculos uniformes"""
        self.ensure_one()
        return self.product_uom_id._compute_quantity(
            self.actual_qty, 
            self.product_id.uom_id,
            round=False
        )
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Actualiza la UdM cuando cambia el producto"""
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id
            
    @api.onchange('is_waste')
    def _onchange_is_waste(self):
        """Validar ubicación de desecho cuando se marca como tal"""
        if self.is_waste:
            # Verificar que exista ubicación de desecho
            scrap_location = self.env['stock.location'].search([
                ('scrap_location', '=', True),
                ('company_id', 'in', [self.company_id.id, False])
            ], limit=1)
            
            if not scrap_location:
                return {
                    'warning': {
                        'title': _('Configuración requerida'),
                        'message': _(
                            'No hay ubicación de desecho configurada. '
                            'Configure una ubicación de tipo desecho antes de continuar.'
                        )
                    }
                }
            else:
                return {
                    'warning': {
                        'title': _('Producto marcado como desecho'),
                        'message': _(
                            'Este producto no recibirá costo y será movido a: %s',
                            scrap_location.complete_name
                        )
                    }
                }
    
    @api.onchange('use_manual_cost', 'cost_share_manual')
    def _onchange_manual_cost(self):
        """Advertir cuando se usa distribución manual"""
        if self.use_manual_cost and self.cost_share_manual:
            # Forzar recálculo
            self._compute_cost_share()
            
            # Verificar suma total si hay otras líneas manuales
            manual_lines = self.unbuild_id.unbuild_line_ids.filtered(
                lambda l: l.use_manual_cost and not l.is_waste
            )
            if len(manual_lines) > 1:
                total_manual = sum(l.cost_share_manual for l in manual_lines)
                if abs(total_manual - 100.0) > 0.01:
                    return {
                        'warning': {
                            'title': _('Verificar distribución manual'),
                            'message': _(
                                'La suma de distribuciones manuales es %.2f%%. '
                                'Debería ser 100%% para una distribución correcta.',
                                total_manual
                            )
                        }
                    }
    
    @api.constrains('actual_qty')
    def _check_actual_qty(self):
        """Valida que la cantidad real sea positiva"""
        for line in self:
            if float_compare(line.actual_qty, 0, precision_rounding=line.product_uom_id.rounding) < 0:
                raise ValidationError(_('La cantidad real debe ser positiva.'))
    
    @api.constrains('value_factor')
    def _check_value_factor(self):
        """Valida que el factor de valor sea positivo"""
        for line in self:
            if line.value_factor <= 0:
                raise ValidationError(_(
                    'El factor de valor debe ser mayor que cero. '
                    'Use 1.0 para valor estándar.'
                ))
    
    @api.constrains('cost_share_manual', 'use_manual_cost')
    def _check_manual_cost(self):
        """Valida los valores de distribución manual"""
        for line in self:
            if line.use_manual_cost and line.cost_share_manual:
                if line.cost_share_manual < 0 or line.cost_share_manual > 100:
                    raise ValidationError(_(
                        'El porcentaje de distribución manual debe estar entre 0 y 100.'
                    ))
    
    @api.constrains('is_waste')
    def _check_waste_location(self):
        """Valida que exista ubicación de desecho si hay productos marcados como tal"""
        for line in self:
            if line.is_waste:
                scrap_location = self.env['stock.location'].search([
                    ('scrap_location', '=', True),
                    ('company_id', 'in', [line.company_id.id, False])
                ], limit=1)
                
                if not scrap_location:
                    raise UserError(_(
                        'No se puede marcar como desecho. '
                        'No hay ubicación de desecho configurada en el sistema.'
                    ))