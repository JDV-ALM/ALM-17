# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    manufacturing_alt_cost = fields.Monetary(
        string='Manufacturing Alt. Cost',
        compute='_compute_manufacturing_alt_cost',
        store=True,
        currency_field='alt_currency_id',
        help='Manufacturing cost calculated from BOM components alternative costs'
    )
    
    manufacturing_cost_state = fields.Selection([
        ('ok', 'OK'),
        ('warning', 'Warning'),
        ('no_bom', 'No BOM'),
        ('empty_bom', 'Empty BOM'),
    ], string='Manufacturing Cost State', 
       compute='_compute_manufacturing_alt_cost', 
       store=True,
       help='State of the manufacturing cost calculation')

    @api.depends('product_variant_ids', 'product_variant_ids.manufacturing_alt_cost', 'product_variant_ids.manufacturing_cost_state')
    def _compute_manufacturing_alt_cost(self):
        """Compute manufacturing alternative cost from variants"""
        unique_variants = self.filtered(lambda template: len(template.product_variant_ids) == 1)
        for template in unique_variants:
            variant = template.product_variant_ids[0]
            template.manufacturing_alt_cost = variant.manufacturing_alt_cost
            template.manufacturing_cost_state = variant.manufacturing_cost_state
        
        # Templates with multiple variants or no variants
        (self - unique_variants).update({
            'manufacturing_alt_cost': 0.0,
            'manufacturing_cost_state': 'no_bom'
        })