# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from . import models


def post_init_hook(env):
    """
    Hook de post-instalación para configurar datos iniciales
    """
    # Crear tipos de operación de desposte para almacenes existentes
    warehouses = env['stock.warehouse'].search([])
    warehouses.create_unbuild_picking_type()
    
    # Asignar permisos de desposte a usuarios MRP existentes
    mrp_users = env.ref('mrp.group_mrp_user').users
    unbuild_group = env.ref('mrp_unbuild.group_mrp_unbuild_user')  # Corregido: agregado prefijo del módulo
    if unbuild_group:
        mrp_users.write({'groups_id': [(4, unbuild_group.id)]})
    
    # Asignar permisos de manager de desposte a managers MRP
    mrp_managers = env.ref('mrp.group_mrp_manager').users
    unbuild_manager_group = env.ref('mrp_unbuild.group_mrp_unbuild_manager')  # Corregido: agregado prefijo del módulo
    if unbuild_manager_group:
        mrp_managers.write({'groups_id': [(4, unbuild_manager_group.id)]})
    
    # Crear cuenta contable por defecto para pérdidas de desposte si no existe
    companies = env['res.company'].search([])
    for company in companies:
        # Buscar cuenta de pérdidas existente o crear una nueva
        loss_account = env['account.account'].search([
            ('code', '=', '659999'),
            ('company_id', '=', company.id)
        ], limit=1)
        
        if not loss_account and company.chart_template:
            # Crear cuenta para pérdidas de desposte
            loss_account = env['account.account'].create({
                'code': '659999',
                'name': 'Unbuild Process Losses',
                'account_type': 'expense_direct_cost',
                'company_id': company.id,
                'reconcile': False,
            })
            
            # Guardar en parámetro de configuración
            env['ir.config_parameter'].sudo().set_param(
                'mrp.unbuild.loss_account_id.%s' % company.id,
                loss_account.id
            )