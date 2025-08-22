# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Developer: Almus Dev (JDV-ALM) - www.almus.dev

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare
from decimal import Decimal, ROUND_DOWN
import logging

_logger = logging.getLogger(__name__)


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
        help="Factor multiplicador para distribución de costos.\n"
             "Rango: 0.01 a 100.00"
    )
    
    # Campo de no distribución desde BoM
    no_cost_distribution_bom = fields.Boolean(
        string='No Distribuir (BoM)',
        readonly=True,
        help="Configuración original de la lista de materiales"
    )
    
    # Campo de no distribución ajustable
    no_cost_distribution = fields.Boolean(
        string='No Distribuir Costos',
        default=False,
        help="Si está marcado, este producto no recibirá costos del desmantelamiento"
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
    
    # Campo para hacer readonly en estado ready/done
    state = fields.Selection(
        related='unbuild_id.state',
        string='Estado',
        store=False
    )
    
    @api.depends('actual_qty', 'value_factor', 'is_waste', 'no_cost_distribution',
                 'unbuild_id.unbuild_line_ids.actual_qty', 
                 'unbuild_id.unbuild_line_ids.value_factor',
                 'unbuild_id.unbuild_line_ids.is_waste',
                 'unbuild_id.unbuild_line_ids.no_cost_distribution')
    def _compute_cost_share(self):
        """Calcula la distribución del costo considerando el factor de valor y exclusiones"""
        for record in self.mapped('unbuild_id'):
            lines = record.unbuild_line_ids
            
            # Filtrar líneas que SÍ reciben costo
            cost_lines = lines.filtered(
                lambda l: not l.is_waste 
                and not l.no_cost_distribution 
                and l.actual_qty > 0
            )
            
            if not cost_lines:
                # Si no hay líneas que reciban costo, todas a 0
                for line in lines:
                    line.cost_share = 0.0
                continue
            
            # Calcular pesos con precisión decimal
            weights = []
            for line in cost_lines:
                qty_base = Decimal(str(line._get_qty_in_base_uom()))
                factor = Decimal(str(line.value_factor))
                weights.append({
                    'line_id': line.id,
                    'weight': qty_base * factor,
                    'line': line
                })
            
            total_weight = sum(w['weight'] for w in weights)
            
            if total_weight <= 0:
                for line in lines:
                    line.cost_share = 0.0
                continue
            
            # Ordenar por peso (mayor al final para absorber diferencias)
            weights.sort(key=lambda x: x['weight'])
            
            # Calcular shares garantizando suma = 1.0
            accumulated = Decimal('0')
            shares = {}
            
            # Procesar todos menos el último
            for item in weights[:-1]:
                share = (item['weight'] / total_weight).quantize(
                    Decimal('0.0001'), 
                    rounding=ROUND_DOWN
                )
                shares[item['line_id']] = float(share)
                accumulated += share
            
            # El último absorbe la diferencia para garantizar suma = 1.0
            if weights:
                last_item = weights[-1]
                shares[last_item['line_id']] = float(Decimal('1.0') - accumulated)
            
            # Asignar valores
            for line in lines:
                if line.is_waste or line.no_cost_distribution:
                    line.cost_share = 0.0
                else:
                    line.cost_share = shares.get(line.id, 0.0)
            
            # Log para debugging
            total_assigned = sum(shares.values()) if shares else 0.0
            if shares and abs(total_assigned - 1.0) > 0.0001:
                _logger.warning(
                    'Distribución de costos para %s: suma = %.6f (esperado: 1.0)',
                    record.name, total_assigned
                )
    
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
        """Ajusta configuración cuando se marca como desecho"""
        if self.is_waste:
            self.no_cost_distribution = True
            self.value_factor = 0.0
            
            # Verificar que exista ubicación de desecho
            if self.company_id:
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
    
    @api.onchange('no_cost_distribution')
    def _onchange_no_cost_distribution(self):
        """Ajusta el factor cuando se marca/desmarca no distribuir costos"""
        if self.no_cost_distribution:
            self.value_factor = 0.0
        elif self.value_factor == 0.0 and not self.is_waste:
            self.value_factor = self.value_factor_bom or 1.0
    
    @api.constrains('actual_qty')
    def _check_actual_qty(self):
        """Valida que la cantidad real sea positiva o cero solo para desechos"""
        for line in self:
            if line.actual_qty < 0:
                raise ValidationError(_('La cantidad real no puede ser negativa.'))
            
            if line.actual_qty == 0 and not line.is_waste:
                # Permitir cantidad 0 solo si está marcado como no distribuir costos
                if not line.no_cost_distribution:
                    raise ValidationError(_(
                        'El producto %s tiene cantidad 0. '
                        'Debe establecer una cantidad, marcarlo como desecho, '
                        'o marcar "No Distribuir Costos".'
                    ) % line.product_id.display_name)
    
    @api.constrains('value_factor')
    def _check_value_factor(self):
        """Valida que el factor de valor esté en rango permitido"""
        for line in self:
            # Si no distribuye costos o es desecho, no validar
            if line.no_cost_distribution or line.is_waste:
                continue
                
            if line.value_factor < 0.01 or line.value_factor > 100:
                raise ValidationError(_(
                    'El factor de valor para %s debe estar entre 0.01 y 100.00\n'
                    'Valor actual: %.2f'
                ) % (line.product_id.display_name, line.value_factor))