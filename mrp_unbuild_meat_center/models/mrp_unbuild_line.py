# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Developer: Almus Dev (JDV-ALM) - www.almus.dev

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
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
    
    @api.depends('actual_qty', 'is_waste', 'unbuild_id.unbuild_line_ids.actual_qty', 'unbuild_id.unbuild_line_ids.is_waste')
    def _compute_cost_share(self):
        """Calcula la distribución proporcional del costo entre productos no-desecho"""
        for line in self:
            if line.is_waste:
                line.cost_share = 0.0
            else:
                # Calcular total de productos buenos (no desecho)
                good_lines = line.unbuild_id.unbuild_line_ids.filtered(lambda l: not l.is_waste)
                total_good_qty = sum(good_lines.mapped(lambda l: l._get_qty_in_base_uom()))
                
                if total_good_qty > 0:
                    line_qty_base = line._get_qty_in_base_uom()
                    line.cost_share = (line_qty_base / total_good_qty)
                else:
                    line.cost_share = 0.0
    
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
        """Si se marca como desecho, avisar que no tendrá costo"""
        if self.is_waste:
            return {
                'warning': {
                    'title': _('Producto marcado como desecho'),
                    'message': _('Este producto no recibirá costo y será movido a la ubicación de desecho.')
                }
            }
    
    @api.constrains('actual_qty')
    def _check_actual_qty(self):
        """Valida que la cantidad real sea positiva"""
        for line in self:
            if float_compare(line.actual_qty, 0, precision_rounding=line.product_uom_id.rounding) < 0:
                raise ValidationError(_('La cantidad real debe ser positiva.'))