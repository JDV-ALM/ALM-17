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
            sequence = self.env['ir.sequence'].sudo().create({
                'name': f'{warehouse.name} Unbuild',
                'prefix': f'{warehouse.code}/UO/',
                'padding': 5,
                'company_id': warehouse.company_id.id,
            })
            
            # Crear tipo de operación
            picking_type_vals = {
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
                'barcode': f'{warehouse.code}UO',  # Agregado código de barras
            }
            
            picking_type = self.env['stock.picking.type'].sudo().create(picking_type_vals)
            warehouse.unbuild_type_id = picking_type
            
            # Crear regla de ruta si es necesario
            route = self.env.ref('mrp_unbuild.route_unbuild', raise_if_not_found=False)
            if route:
                # Asociar la ruta con el almacén
                route.write({'warehouse_ids': [(4, warehouse.id)]})
                
                # Crear regla de stock para la ruta
                rule_vals = {
                    'name': f'{warehouse.name}: Unbuild',
                    'route_id': route.id,
                    'picking_type_id': picking_type.id,
                    'location_src_id': warehouse.lot_stock_id.id,
                    'location_dest_id': warehouse.lot_stock_id.id,
                    'action': 'pull',
                    'procure_method': 'make_to_order',
                    'company_id': warehouse.company_id.id,
                    'warehouse_id': warehouse.id,
                    'propagate_cancel': True,
                }
                self.env['stock.rule'].sudo().create(rule_vals)
    
    @api.model_create_multi
    def create(self, vals_list):
        warehouses = super().create(vals_list)
        warehouses.create_unbuild_picking_type()
        return warehouses
    
    def write(self, vals):
        res = super().write(vals)
        # Si se activa el almacén y no tiene tipo de desposte, crearlo
        if vals.get('active') and not self.unbuild_type_id:
            self.create_unbuild_picking_type()
        return res
    
    def _get_picking_type_update_values(self):
        """Extender para actualizar tipos de picking de desposte"""
        res = super()._get_picking_type_update_values()
        if self.unbuild_type_id:
            res[self.unbuild_type_id.id] = {
                'default_location_src_id': self.lot_stock_id.id,
                'default_location_dest_id': self.lot_stock_id.id,
            }
        return res
    
    def _get_picking_type_create_values(self, max_sequence):
        """Extender para incluir tipo de desposte en la creación"""
        res = super()._get_picking_type_create_values(max_sequence)
        # El tipo de desposte se crea mediante create_unbuild_picking_type
        return res
    
    def _create_or_update_sequences_and_picking_types(self):
        """Extender para asegurar que se creen tipos de desposte"""
        res = super()._create_or_update_sequences_and_picking_types()
        # Crear tipos de desposte para almacenes que no los tengan
        self.filtered(lambda w: not w.unbuild_type_id).create_unbuild_picking_type()
        return res


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'
    
    # Campo para identificar tipos de picking de desposte
    is_unbuild_type = fields.Boolean(
        string='Is Unbuild Type',
        compute='_compute_is_unbuild_type',
        store=True
    )
    
    @api.depends('code', 'sequence_code')
    def _compute_is_unbuild_type(self):
        for picking_type in self:
            picking_type.is_unbuild_type = (
                picking_type.code == 'mrp_operation' and 
                picking_type.sequence_code == 'UO'
            )
    
    def _compute_picking_count(self):
        """Extender para contar pickings de desposte correctamente"""
        super()._compute_picking_count()
        # Los tipos de desposte deben contar órdenes de producción tipo unbuild
        for record in self.filtered('is_unbuild_type'):
            domain = [
                ('state', 'not in', ('done', 'cancel')),
                ('is_unbuild_order', '=', True),
                ('picking_type_id', '=', record.id),
            ]
            record.count_picking_draft = self.env['mrp.production'].search_count(domain + [('state', '=', 'draft')])
            record.count_picking_ready = self.env['mrp.production'].search_count(domain + [('state', '=', 'confirmed')])
            record.count_picking_waiting = self.env['mrp.production'].search_count(domain + [('state', '=', 'progress')])
            record.count_picking = record.count_picking_draft + record.count_picking_ready + record.count_picking_waiting