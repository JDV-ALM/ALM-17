# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class AlmusCostRecalculationWizard(models.TransientModel):
    _name = 'almus.cost.recalculation.wizard'
    _description = 'Alternative Cost Recalculation Wizard'

    products_count = fields.Integer(
        string='Products to Update',
        readonly=True,
        help='Number of products that will be updated'
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        readonly=True,
        help='Alternative currency to use for recalculation'
    )
    
    def action_confirm_recalculation(self):
        """Confirm and execute the recalculation"""
        self.ensure_one()
        
        # Execute recalculation
        self.env['product.product'].sudo().action_recalculate_alt_costs()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Alternative costs have been recalculated for %s products.') % self.products_count,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window_close'
                }
            }
        }