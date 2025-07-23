# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    alt_currency_id = fields.Many2one(
        'res.currency',
        string='Alternative Currency',
        compute='_compute_alt_currency_fields',
        readonly=False,
        store=True,
        help='Alternative currency used to display cost'
    )
    
    alt_cost = fields.Monetary(
        string='Cost in Alt. Currency',
        compute='_compute_alt_currency_fields',
        store=True,
        currency_field='alt_currency_id',
        help='Product cost converted to the alternative currency'
    )

    @api.depends('product_variant_ids', 'product_variant_ids.alt_currency_id', 'product_variant_ids.alt_cost')
    def _compute_alt_currency_fields(self):
        """Compute alternative currency fields from variants"""
        unique_variants = self.filtered(lambda template: len(template.product_variant_ids) == 1)
        for template in unique_variants:
            variant = template.product_variant_ids[0]
            template.alt_currency_id = variant.alt_currency_id
            template.alt_cost = variant.alt_cost
        
        # Templates with multiple variants or no variants
        (self - unique_variants).update({
            'alt_currency_id': False,
            'alt_cost': 0.0
        })