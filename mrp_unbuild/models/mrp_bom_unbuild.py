# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    # Extender el campo type para incluir 'unbuild'
    type = fields.Selection(
        selection_add=[('unbuild', 'Unbuild')],
        ondelete={'unbuild': 'cascade'},
        help="BoM Type:\n"
             "- Manufacture: Used to manufacture the product\n"
             "- Kit: Used to sell a set of products as one\n"
             "- Unbuild: Used to disassemble a product into components"
    )
    
    # Campo para indicar si es un BoM de desposte
    is_unbuild = fields.Boolean(
        string='Is Unbuild BoM',
        compute='_compute_is_unbuild',
        store=True
    )
    
    # En desposte, los componentes son productos de salida
    unbuild_line_ids = fields.One2many(
        'mrp.bom.line', 'bom_id',
        string='Output Products',
        compute='_compute_unbuild_lines',
        inverse='_inverse_unbuild_lines'
    )
    
    # Configuración específica para desposte
    unbuild_yield_ids = fields.One2many(
        'mrp.bom.unbuild.yield', 'bom_id',
        string='Expected Yields',
        help="Define expected yield percentages for each output product"
    )
    
    @api.depends('type')
    def _compute_is_unbuild(self):
        for bom in self:
            bom.is_unbuild = bom.type == 'unbuild'
    
    @api.depends('bom_line_ids', 'type')
    def _compute_unbuild_lines(self):
        for bom in self:
            if bom.type == 'unbuild':
                bom.unbuild_line_ids = bom.bom_line_ids
            else:
                bom.unbuild_line_ids = False
    
    def _inverse_unbuild_lines(self):
        for bom in self:
            if bom.type == 'unbuild':
                bom.bom_line_ids = bom.unbuild_line_ids
    
    @api.constrains('type', 'bom_line_ids', 'byproduct_ids')
    def _check_unbuild_constraints(self):
        for bom in self:
            if bom.type == 'unbuild':
                # En desposte no hay byproducts, todos son productos principales
                if bom.byproduct_ids:
                    raise ValidationError(_("Unbuild BoMs cannot have by-products. All outputs should be defined as main products."))
                
                # Validar que la suma de cost_share no exceda 100%
                total_cost_share = sum(bom.unbuild_yield_ids.mapped('cost_share'))
                if total_cost_share > 100:
                    raise ValidationError(_("The total cost share cannot exceed 100%%."))
    
    @api.onchange('type')
    def _onchange_type_unbuild(self):
        if self.type == 'unbuild':
            # Limpiar byproducts si se cambia a tipo unbuild
            self.byproduct_ids = [(5, 0, 0)]
            # Cambiar el string del campo para mejor UX
            self._fields['bom_line_ids'].string = 'Output Products'
        else:
            self._fields['bom_line_ids'].string = 'Components'
    
    def _get_flattened_totals(self, bom_ids=None):
        """Override para manejar BoMs de tipo unbuild"""
        if self.type == 'unbuild':
            # Para unbuild, no aplicamos la lógica de explosión
            return {}
        return super()._get_flattened_totals(bom_ids)


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'
    
    # Campo para indicar si esta línea pertenece a un BoM de desposte
    is_unbuild_line = fields.Boolean(
        related='bom_id.is_unbuild',
        store=True
    )
    
    # En desposte, esto representa el rendimiento esperado
    expected_yield = fields.Float(
        string='Expected Yield %',
        default=100.0,
        help="Expected yield percentage for this output product in unbuild process"
    )
    
    @api.constrains('product_qty')
    def _check_unbuild_qty(self):
        for line in self:
            if line.is_unbuild_line and line.product_qty <= 0:
                raise ValidationError(_("Output product quantities must be positive."))


class MrpBomUnbuildYield(models.Model):
    """Modelo para gestionar rendimientos esperados en desposte"""
    _name = 'mrp.bom.unbuild.yield'
    _description = 'Unbuild BoM Expected Yields'
    _order = 'sequence, id'
    
    bom_id = fields.Many2one(
        'mrp.bom',
        string='BoM',
        required=True,
        ondelete='cascade',
        domain=[('type', '=', 'unbuild')]
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        domain="[('type', 'in', ['product', 'consu'])]"
    )
    
    sequence = fields.Integer(
        string='Sequence',
        default=10
    )
    
    expected_qty = fields.Float(
        string='Expected Quantity',
        required=True,
        default=1.0,
        help="Expected quantity per unit of input product"
    )
    
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True,
        domain="[('category_id', '=', product_uom_category_id)]"
    )
    
    product_uom_category_id = fields.Many2one(
        related='product_id.uom_id.category_id'
    )
    
    cost_share = fields.Float(
        string='Cost Share %',
        default=0.0,
        help="Percentage of the input cost to allocate to this product"
    )
    
    is_waste = fields.Boolean(
        string='Is Waste/Loss',
        default=False,
        help="Mark if this represents waste or loss (no cost allocation)"
    )
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id
    
    @api.constrains('cost_share')
    def _check_cost_share(self):
        for record in self:
            if record.cost_share < 0 or record.cost_share > 100:
                raise ValidationError(_("Cost share must be between 0 and 100."))