# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    product_alt_currency_id = fields.Many2one(
        'res.currency',
        string='Product Alternative Currency',
        help='Default currency to display product costs in alternative currency',
        config_parameter='almus_product_cost_currency.alt_currency_id'
    )
    
    # Technical field to show info about last update
    alt_currency_last_update = fields.Char(
        string='Last Currency Update',
        compute='_compute_alt_currency_last_update',
        help='Information about the last alternative currency update'
    )

    @api.depends('product_alt_currency_id')
    def _compute_alt_currency_last_update(self):
        """Show information about products using alternative currency"""
        for record in self:
            if record.product_alt_currency_id:
                count = self.env['product.product'].search_count([
                    ('alt_currency_id', '=', record.product_alt_currency_id.id)
                ])
                record.alt_currency_last_update = _(
                    '%(count)s products are using %(currency)s as alternative currency',
                    count=count,
                    currency=record.product_alt_currency_id.name
                )
            else:
                record.alt_currency_last_update = _('No alternative currency configured')

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
            # Log the change
            if old_currency_id:
                old_currency = self.env['res.currency'].browse(old_currency_id)
                _logger.info(
                    "Alternative currency changed from %s to %s. Updating all products...",
                    old_currency.name,
                    self.product_alt_currency_id.name
                )
            else:
                _logger.info(
                    "Alternative currency set to %s. Updating all products...",
                    self.product_alt_currency_id.name
                )
            
            # Update products in background
            self.env['product.product'].sudo()._update_alt_currency_from_settings(new_currency_id)

    def action_recalculate_alt_costs(self):
        """Action to recalculate all alternative costs"""
        self.ensure_one()
        
        if not self.product_alt_currency_id:
            raise UserError(_('Please configure an alternative currency first.'))
        
        # Check if user has rights to modify products
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError(_('You need Stock Manager rights to recalculate costs.'))
        
        # Save current settings first
        self.set_values()
        
        # Get products count
        products_count = self.env['product.product'].search_count([
            ('alt_currency_id', '!=', False)
        ])
        
        if products_count == 0:
            raise UserError(_('No products found with alternative currency configured.'))
        
        # Show confirmation dialog for large datasets
        if products_count > 1000:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'almus.cost.recalculation.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_products_count': products_count,
                    'default_currency_id': self.product_alt_currency_id.id,
                }
            }
        else:
            # For smaller datasets, show confirmation dialog
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'almus.cost.recalculation.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_products_count': products_count,
                    'default_currency_id': self.product_alt_currency_id.id,
                }
            }

    def action_view_products_alt_currency(self):
        """Action to view products using alternative currency"""
        self.ensure_one()
        
        if not self.product_alt_currency_id:
            raise UserError(_('Please configure an alternative currency first.'))
            
        return {
            'type': 'ir.actions.act_window',
            'name': _('Products with Alternative Currency'),
            'res_model': 'product.product',
            'view_mode': 'tree,form',
            'domain': [('alt_currency_id', '=', self.product_alt_currency_id.id)],
            'context': {
                'search_default_filter_active': 1,
            }
        }