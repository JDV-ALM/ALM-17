# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Developer: Almus Dev (JDV-ALM) - www.almus.dev

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare


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
    
    # Factor de valor inicial desde la BoM
    value_factor_bom = fields.Float(
        string='Factor BoM',
        default=1.0,
        digits=(12, 2),
        readonly=True,
        help="Factor de valor original definido en la lista de materiales"
    )
    
    # Factor de valor ajustable
    value_factor = fields.Float(
        string='Factor de Valor',
        default=1.0,
        digits=(12, 2),
        help="Factor multiplicador para distribución de costos"
    )
    
    # Distribución de costo calculada
    cost_share = fields.Float(
        string='Distribución de Costo (%)',
        digits=(5, 2),
        compute='_compute_cost_share',
        store=True,
        help="Porcentaje del costo total asignado a este producto"
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
                 'unbuild_id.unbuild_line_ids.is_waste')
    def _compute_cost_share(self):
        """Calcula la distribución del costo considerando el factor de valor"""
        for line in self:
            if line.is_waste:
                line.cost_share = 0.0
            else:
                # Obtener líneas válidas (no desecho)
                if line.unbuild_id:
                    good_lines = line.unbuild_id.unbuild_line_ids.filtered(lambda l: not l.is_waste)
                    
                    # Calcular suma ponderada total
                    total_weighted_value = 0.0
                    for good_line in good_lines:
                        qty_base = good_line._get_qty_in_base_uom()
                        total_weighted_value += qty_base * good_line.value_factor
                    
                    if total_weighted_value > 0:
                        line_qty_base = line._get_qty_in_base_uom()
                        line_weighted_value = line_qty_base * line.value_factor
                        line.cost_share = line_weighted_value / total_weighted_value
                    else:
                        line.cost_share = 0.0
                else:
                    line.cost_share = 0.0
    
    @api.depends('actual_qty', 'value_factor')
    def _compute_relative_value(self):
        """Calcula el valor relativo del producto"""
        for line in self:
            line.relative_value = line.actual_qty * line.value_factor
    
    def _get_qty_in_base_uom(self):
        """Convierte la cantidad a la UdM base del producto"""
        self.ensure_one()
        if self.product_id and self.product_uom_id:
            return self.product_uom_id._compute_quantity(
                self.actual_qty, 
                self.product_id.uom_id,
                round=False
            )
        return 0.0
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Actualiza la UdM cuando cambia el producto"""
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id
    
    @api.onchange('is_waste')
    def _onchange_is_waste(self):
        """Validar ubicación de desecho cuando se marca como tal"""
        if self.is_waste and self.company_id:
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
    
    @api.onchange('value_factor')
    def _onchange_value_factor(self):
        """Advertir cuando se modifica el factor de valor"""
        if self.value_factor_bom > 0 and self.value_factor != self.value_factor_bom:
            return {
                'warning': {
                    'title': _('Factor de valor modificado'),
                    'message': _(
                        'Has modificado el factor de valor. '
                        'Valor original de la BoM: %.2f',
                        self.value_factor_bom
                    )
                }
            }
    
    @api.constrains('actual_qty')
    def _check_actual_qty(self):
        """Valida que la cantidad real sea positiva"""
        for line in self:
            if line.product_uom_id and float_compare(line.actual_qty, 0, 
                                                     precision_rounding=line.product_uom_id.rounding) < 0:
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
    
    @api.constrains('is_waste')
    def _check_waste_location(self):
        """Valida que exista ubicación de desecho si hay productos marcados como tal"""
        for line in self:
            if line.is_waste and line.company_id:
                scrap_location = self.env['stock.location'].search([
                    ('scrap_location', '=', True),
                    ('company_id', 'in', [line.company_id.id, False])
                ], limit=1)
                
                if not scrap_location:
                    raise UserError(_(
                        'No se puede marcar como desecho. '
                        'No hay ubicación de desecho configurada en el sistema.'
                    ))