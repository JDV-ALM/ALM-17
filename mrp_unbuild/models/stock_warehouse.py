# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'
    
    # Tipo de operación para desposte
    unbuild_type_id = fields.Many2one(
        'stock.picking.type',
        string='Unbuild Operation Type',
        check_company=True
    )
    
    def create_unbuild_picking_type(self):
        """Crear tipo de operación para desposte en cada almacén"""
        for warehouse in self:
            if warehouse.unbuild_type_id:
                continue
            
            # Crear secuencia específica para este almacén
            sequence = self.env['ir.sequence'].create({
                'name': f'{warehouse.name} Unbuild',
                'prefix': f'{warehouse.code}/UO/',
                'padding': 5,
                'company_id': warehouse.company_id.id,
            })
            
            # Crear tipo de operación
            picking_type = self.env['stock.picking.type'].create({
                'name': _('Unbuild Orders'),
                'code': 'mrp_operation',
                'sequence_id': sequence.id,
                'sequence_code': 'UO',
                'warehouse_id': warehouse.id,
                'company_id': warehouse.company_id.id,
                'use_create_lots': True,
                'use_existing_lots': True,
                'default_location_src_id': warehouse.lot_stock_id.id,
                'default_location_dest_id': warehouse.lot_stock_id.id,
                'show_operations': True,
                'show_reserved': True,
            })
            
            warehouse.unbuild_type_id = picking_type
    
    @api.model_create_multi
    def create(self, vals_list):
        warehouses = super().create(vals_list)
        warehouses.create_unbuild_picking_type()
        return warehouses


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    group_unbuild_strict_yields = fields.Boolean(
        string="Strict Yield Control",
        implied_group='mrp.group_mrp_user',  # Cambiar a un grupo existente
        help="Enforce that actual yields match expected yields within tolerance"
    )
    
    unbuild_allow_backorder = fields.Boolean(
        string="Allow Unbuild Backorders",
        config_parameter='mrp.unbuild.allow_backorder',
        default=True,
        help="Allow creating backorders when unbuild quantities are partial"
    )
    
    unbuild_yield_tolerance = fields.Float(
        string="Yield Tolerance %",
        config_parameter='mrp.unbuild.yield_tolerance',
        default=5.0,
        help="Acceptable variance percentage for unbuild yields"
    )