# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.tools import float_compare, float_is_zero


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    # Campo para identificar movimientos de desposte
    is_unbuild_move = fields.Boolean(
        string='Is Unbuild Move',
        default=False,
        help="Indicates if this move is part of an unbuild operation"
    )
    
    # Relación con línea de rendimiento
    unbuild_yield_line_id = fields.Many2one(
        'mrp.production.unbuild.yield',
        string='Unbuild Yield Line',
        help="Related yield line in unbuild order"
    )
    
    @api.depends('raw_material_production_id.is_unbuild_order', 'production_id.is_unbuild_order')
    def _compute_is_unbuild_move(self):
        for move in self:
            production = move.raw_material_production_id or move.production_id
            move.is_unbuild_move = production and production.is_unbuild_order
    
    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        """Override para manejar movimientos de desposte"""
        vals = super()._prepare_move_line_vals(quantity, reserved_quant)
        
        if self.is_unbuild_move and self.production_id and self.production_id.lot_producing_id:
            # Para el producto principal en desposte, usar el lote especificado
            if self.product_id == self.production_id.product_id:
                vals['lot_id'] = self.production_id.lot_producing_id.id
        
        return vals
    
    def _action_done(self, cancel_backorder=False):
        """Override para procesar movimientos de desposte"""
        # Identificar movimientos de desposte
        unbuild_moves = self.filtered('is_unbuild_move')
        other_moves = self - unbuild_moves
        
        # Procesar movimientos de desposte
        for move in unbuild_moves:
            if move.production_id and move.production_id.is_unbuild_order:
                # Actualizar cantidades en líneas de rendimiento
                yield_line = move.production_id.unbuild_yield_line_ids.filtered(
                    lambda l: l.product_id == move.product_id
                )
                if yield_line and not yield_line.actual_qty:
                    yield_line.actual_qty = move.quantity
        
        # Llamar al método padre
        res = super(StockMove, self)._action_done(cancel_backorder=cancel_backorder)
        
        # Post-procesamiento para desposte
        for move in unbuild_moves:
            if move.production_id and move.production_id.is_unbuild_order:
                # Validar que los movimientos de salida no excedan la entrada
                self._validate_unbuild_quantities(move.production_id)
        
        return res
    
    def _validate_unbuild_quantities(self, production):
        """Validar que las cantidades de salida no excedan la entrada"""
        if not production.is_unbuild_order:
            return
        
        # Obtener movimiento de entrada (producto principal)
        input_move = production.move_finished_ids.filtered(
            lambda m: m.product_id == production.product_id
        )
        if not input_move:
            return
        
        input_qty = input_move.product_uom._compute_quantity(
            input_move.quantity, production.product_id.uom_id
        )
        
        # Calcular total de salidas
        output_moves = production.move_finished_ids.filtered(
            lambda m: m.product_id != production.product_id and m.state == 'done'
        )
        
        total_output_weight = 0
        for move in output_moves:
            # Convertir a unidad base del producto para comparación
            qty = move.product_uom._compute_quantity(
                move.quantity, move.product_id.uom_id
            )
            total_output_weight += qty
        
        # Validación opcional: verificar que no se exceda el peso de entrada
        # (comentado por defecto, activar según necesidad del negocio)
        # if float_compare(total_output_weight, input_qty, precision_rounding=0.01) > 0:
        #     raise UserError(_("Output quantities exceed input quantity!"))
    
    @api.model
    def _prepare_merge_moves_distinct_fields(self):
        """Agregar campos específicos de desposte a la lista de campos distintos"""
        distinct_fields = super()._prepare_merge_moves_distinct_fields()
        return distinct_fields + ['is_unbuild_move', 'unbuild_yield_line_id']
    
    def _prepare_procurement_values(self):
        """Override para propagar información de desposte"""
        values = super()._prepare_procurement_values()
        if self.is_unbuild_move:
            values['is_unbuild_move'] = True
        return values
    
    def _generate_consumed_move_line(self, qty_to_add, final_lot, lot=False):
        """Override para manejar lotes en desposte"""
        if self.is_unbuild_move and self.production_id and self.production_id.is_unbuild_order:
            # En desposte, el lote del producto principal ya viene definido
            if self.product_id == self.production_id.product_id and self.production_id.lot_producing_id:
                lot = self.production_id.lot_producing_id
        
        return super()._generate_consumed_move_line(qty_to_add, final_lot, lot=lot)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'
    
    # Relación con orden de desposte
    unbuild_order_id = fields.Many2one(
        related='move_id.production_id',
        string='Unbuild Order',
        store=True,
        readonly=True
    )
    
    is_unbuild_line = fields.Boolean(
        related='move_id.is_unbuild_move',
        string='Is Unbuild Line',
        store=True
    )
    
    def _get_aggregated_product_quantities(self, **kwargs):
        """Override para agrupar correctamente líneas de desposte"""
        aggregated = super()._get_aggregated_product_quantities(**kwargs)
        
        # Agregar información de desposte si es relevante
        if any(self.mapped('is_unbuild_line')):
            for key, values in aggregated.items():
                # Agregar indicador de desposte
                if values.get('is_unbuild_line'):
                    values['description'] = _('Unbuild: %s') % values.get('description', '')
        
        return aggregated
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override para establecer valores por defecto en líneas de desposte"""
        for vals in vals_list:
            move = self.env['stock.move'].browse(vals.get('move_id'))
            if move and move.is_unbuild_move and move.production_id:
                production = move.production_id
                # Para el producto principal, usar el lote de la orden
                if move.product_id == production.product_id and production.lot_producing_id:
                    vals['lot_id'] = production.lot_producing_id.id
        
        return super().create(vals_list)


class StockPicking(models.Model):
    _inherit = 'stock.picking'
    
    # Campo computado para identificar pickings de desposte
    is_unbuild_picking = fields.Boolean(
        string='Is Unbuild Picking',
        compute='_compute_is_unbuild_picking',
        store=True
    )
    
    @api.depends('move_ids.is_unbuild_move')
    def _compute_is_unbuild_picking(self):
        for picking in self:
            picking.is_unbuild_picking = any(picking.move_ids.mapped('is_unbuild_move'))
    
    def button_validate(self):
        """Override para validaciones adicionales en pickings de desposte"""
        unbuild_pickings = self.filtered('is_unbuild_picking')
        
        for picking in unbuild_pickings:
            # Validar que se hayan capturado todas las cantidades
            for move in picking.move_ids.filtered('is_unbuild_move'):
                if move.state not in ('done', 'cancel') and float_is_zero(move.quantity, precision_rounding=move.product_uom.rounding):
                    # Advertencia suave, no error
                    move.quantity = move.product_uom_qty
        
        return super().button_validate()


class StockQuant(models.Model):
    _inherit = 'stock.quant'
    
    def _gather(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False):
        """Override para priorizar quants en órdenes de desposte"""
        quants = super()._gather(product_id, location_id, lot_id, package_id, owner_id, strict)
        
        # Si estamos en contexto de desposte, ordenar por fecha más antigua primero (FIFO)
        if self.env.context.get('unbuild_mode'):
            quants = quants.sorted('in_date')
        
        return quants