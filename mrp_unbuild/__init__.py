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
    unbuild_group = env.ref('group_mrp_unbuild_user')
    if unbuild_group:
        mrp_users.write({'groups_id': [(4, unbuild_group.id)]})
    
    # Asignar permisos de manager de desposte a managers MRP
    mrp_managers = env.ref('mrp.group_mrp_manager').users
    unbuild_manager_group = env.ref('group_mrp_unbuild_manager')
    if unbuild_manager_group:
        mrp_managers.write({'groups_id': [(4, unbuild_manager_group.id)]})