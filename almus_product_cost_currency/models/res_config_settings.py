# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    product_alt_currency_id = fields.Many2one(
        'res.currency',
        string='Product Alternative Currency',
        help='Default currency to display product costs in alternative currency',
        config_parameter='almus_product_cost_currency.alt_currency_id'
    )

    def set_values(self):
        """Override to update all products when currency changes"""
        # Get current value before saving
        old_currency_id = int(self.env['ir.config_parameter'].sudo().get_param(
            'almus_product_cost_currency.alt_currency_id', 
            default='0'
        ))
        
        super().set_values()
        
        # Get new value after saving
        new_currency_id = self.product_alt_currency_id.id
        
        # If currency changed, update all products
        if old_currency_id != new_currency_id and new_currency_id:
            self.env['product.product'].sudo()._update_alt_currency_from_settings(new_currency_id)