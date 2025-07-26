# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    # Grupo para control estricto de rendimientos
    group_unbuild_strict_yields = fields.Boolean(
        string="Strict Yield Control",
        group='mrp_unbuild.group_mrp_unbuild_manager',  # Corregido: usar 'group' en lugar de 'implied_group'
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
        config_parameter='mrp.unbuild.loss_account_id',
        help="Account for unallocated costs in unbuild operations",
        domain="[('account_type', '=', 'expense'), ('company_id', '=', company_id)]"
    )