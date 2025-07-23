# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _get_default_alt_currency(self):
        """Get the default alternative currency from settings"""
        param = self.env['ir.config_parameter'].sudo().get_param('almus_product_cost_currency.alt_currency_id')
        if param:
            return int(param)
        # If no parameter set, try to return USD as default
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        return usd.id if usd else False

    alt_currency_id = fields.Many2one(
        'res.currency',
        string='Alternative Currency',
        default=_get_default_alt_currency,
        help='Alternative currency used to display cost'
    )
    
    alt_cost = fields.Monetary(
        string='Cost in Alt. Currency',
        compute='_compute_alt_cost',
        store=True,
        currency_field='alt_currency_id',
        help='Product cost converted to the alternative currency'
    )

    @api.depends('standard_price', 'alt_currency_id', 'company_id', 'alt_currency_id.rate')
    def _compute_alt_cost(self):
        """Compute cost in the alternative currency"""
        for product in self:
            if product.alt_currency_id and product.standard_price:
                # Get the source currency (standard_price is in company currency)
                if product.company_id:
                    from_currency = product.company_id.currency_id
                else:
                    from_currency = self.env.company.currency_id
                
                to_currency = product.alt_currency_id
                
                if from_currency != to_currency:
                    product.alt_cost = from_currency._convert(
                        product.standard_price,
                        to_currency,
                        product.company_id or self.env.company,
                        fields.Date.today()
                    )
                else:
                    product.alt_cost = product.standard_price
            else:
                product.alt_cost = 0.0

    @api.model
    def create(self, vals):
        """Override create to set default alt_currency_id if not provided"""
        if 'alt_currency_id' not in vals:
            vals['alt_currency_id'] = self._get_default_alt_currency()
        return super().create(vals)

    @api.model
    def _update_alt_currency_from_settings(self, currency_id):
        """Update alternative currency for all products when settings change"""
        products = self.search([])
        products.write({'alt_currency_id': currency_id})