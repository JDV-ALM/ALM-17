# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    # Grupo para control estricto de rendimientos
    group_unbuild_strict_yields = fields.Boolean(
        string="Strict Yield Control",
        implied_group='mrp_unbuild.group_unbuild_strict_yields',  # Corregido: usar 'implied_group'
        help="Enforce that actual yields match expected yields within tolerance"
    )
    
    # Permitir backorders en desposte
    unbuild_allow_backorder = fields.Boolean(
        string="Allow Unbuild Backorders",
        config_parameter='mrp.unbuild.allow_backorder',
        default=True,
        help="Allow creating backorders when unbuild quantities are partial"
    )
    
    # Tolerancia de rendimiento
    unbuild_yield_tolerance = fields.Float(
        string="Yield Tolerance %",
        config_parameter='mrp.unbuild.yield_tolerance',
        default=5.0,
        help="Acceptable variance percentage for unbuild yields"
    )
    
    # Validar asignación completa de costos
    unbuild_strict_cost_allocation = fields.Boolean(
        string="Strict Cost Allocation",
        config_parameter='mrp.unbuild.strict_cost_allocation',
        default=False,
        help="Require 100% cost allocation before completing unbuild orders"
    )
    
    # Cuenta para pérdidas no asignadas
    unbuild_loss_account_id = fields.Many2one(
        'account.account',
        string="Unbuild Loss Account",
        help="Account for unallocated costs in unbuild operations",
        domain="[('account_type', '=', 'expense_direct_cost'), ('company_id', '=', company_id)]"
    )
    
    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        
        # Obtener cuenta de pérdidas para la compañía actual
        loss_account_id = ICP.get_param(
            'mrp.unbuild.loss_account_id.%s' % self.env.company.id
        )
        if loss_account_id:
            res['unbuild_loss_account_id'] = int(loss_account_id)
        
        return res
    
    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        
        # Guardar cuenta de pérdidas por compañía
        if self.unbuild_loss_account_id:
            ICP.set_param(
                'mrp.unbuild.loss_account_id.%s' % self.env.company.id,
                self.unbuild_loss_account_id.id
            )