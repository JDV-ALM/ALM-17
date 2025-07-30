# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Using related fields for single variant products
    # This avoids the computed + readonly=False issue
    alt_currency_id = fields.Many2one(
        'res.currency',
        string='Alternative Currency',
        related='product_variant_ids.alt_currency_id',
        readonly=True,
        help='Alternative currency used to display cost (from variant)'
    )
    
    alt_cost = fields.Monetary(
        string='Cost in Alt. Currency',
        related='product_variant_ids.alt_cost',
        readonly=True,
        currency_field='alt_currency_id',
        help='Product cost converted to the alternative currency (from variant)'
    )
    
    # Helper field to know if we should show alt cost fields
    show_alt_cost = fields.Boolean(
        compute='_compute_show_alt_cost',
        help='Technical field to know if alternative cost should be displayed'
    )
    
    @api.depends('product_variant_count', 'alt_currency_id')
    def _compute_show_alt_cost(self):
        """Determine if alternative cost fields should be shown"""
        for template in self:
            # Show only for single variant products with alt currency configured
            template.show_alt_cost = (
                template.product_variant_count == 1 and 
                bool(template.alt_currency_id)
            )