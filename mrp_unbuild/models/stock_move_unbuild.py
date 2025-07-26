# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.tools import float_compare, float_is_zero
from odoo.exceptions import UserError, ValidationError


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    # Campo para identificar movimientos de desposte
    is_unbuild_move = fields.Boolean(
        string='Is Unbuild Move',
        default=False,
        index=True,  # Agregado índice para mejor performance
        help="Indicates if this move is part of an unbuild operation"
    )
    
    # Relación con línea de rendimiento
    unbuild_yield_line_id = fields.Many2one(
        'mrp.production.unbuild.yield',
        string='Unbuild Yield Line',
        index=True,  # Agregado índice
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
        
        # Validar movimientos de desposte antes de procesar
        for move in unbuild_moves:
            if move.production_id and move.production_id.is_unbuild_order:
                # Validar que el movimiento principal tenga cantidad
                if move.product_id == move.production_id.product_id and move.quantity <= 0:
                    raise UserError(_(
                        "Cannot process unbuild order without input quantity for %s"
                    ) % move.product_id.display_name)
        
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
                
                # Actualizar el campo unbuild_yield_line_id si no está establecido
                if not move.unbuild_yield_line_id:
                    yield_line = move.production_id.unbuild_yield_line_ids.filtered(
                        lambda l: l.product_id == move.product_id
                    )
                    if yield_line:
                        move.unbuild_yield_line_id = yield_line
        
        return res
    
    def _validate_unbuild_quantities(self, production):
        """Validar que las cantidades de salida no excedan la entrada"""
        if not production.is_unbuild_order:
            return
        
        # Obtener movimiento de entrada (producto principal)
        input_move = production.move_finished_ids.filtered(
            lambda m: m.product_id == production.product_id and m.state == 'done'
        )
        if not input_move:
            return
        
        input_qty = input_move.product_uom._compute_quantity(
            input_move.quantity, production.product_id.uom_id
        )
        
        # Calcular total de salidas por categoría de peso
        output_moves = production.move_finished_ids.filtered(
            lambda m: m.product_id != production.product_id and m.state == 'done'
        )
        
        # Agrupar por categoría de UoM para validación coherente
        uom_categories = {}
        for move in output_moves:
            category = move.product_uom_id.category_id
            if category not in uom_categories:
                uom_categories[category] = 0
            
            # Convertir a unidad base de la categoría
            qty = move.product_uom._compute_quantity(
                move.quantity, category.uom_ids.filtered('is_base_uom')[0]
            )
            uom_categories[category] += qty
        
        # Validar solo si la entrada y salidas son de la misma categoría (ej: peso)
        input_category = production.product_uom_id.category_id
        if input_category in uom_categories:
            output_qty = uom_categories[input_category]
            
            # Permitir una tolerancia del 1% para redondeos
            tolerance = 0.01
            if float_compare(output_qty, input_qty * (1 + tolerance), 
                           precision_rounding=0.001) > 0:
                raise UserError(_(
                    "Output quantities exceed input quantity!\n"
                    "Input: %s %s\n"
                    "Output: %s %s"
                ) % (
                    input_qty,
                    input_category.name,
                    output_qty,
                    input_category.name
                ))
    
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
    
    def _compute_reserved_availability(self):
        """Override para manejar disponibilidad en movimientos de desposte"""
        unbuild_moves = self.filtered(lambda m: m.is_unbuild_move and m.production_id)
        other_moves = self - unbuild_moves
        
        # Para movimientos de desposte del producto principal, verificar disponibilidad especial
        for move in unbuild_moves:
            if move.product_id == move.production_id.product_id:
                # El producto principal siempre debe estar disponible si existe el stock
                available_qty = self.env['stock.quant']._get_available_quantity(
                    move.product_id,
                    move.location_id,
                    lot_id=move.production_id.lot_producing_id,
                    strict=False
                )
                move.reserved_availability = min(move.product_uom_qty, available_qty)
            else:
                # Para productos de salida, no hay reserva
                move.reserved_availability = 0
        
        # Procesar otros movimientos normalmente
        if other_moves:
            super(StockMove, other_moves)._compute_reserved_availability()


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'
    
    # Relación con orden de desposte
    unbuild_order_id = fields.Many2one(
        related='move_id.production_id',
        string='Unbuild Order',
        store=True,
        index=True,  # Agregado índice
        readonly=True
    )
    
    is_unbuild_line = fields.Boolean(
        related='move_id.is_unbuild_move',
        string='Is Unbuild Line',
        store=True,
        index=True  # Agregado índice
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
    
    @api.constrains('lot_id', 'move_id')
    def _check_unbuild_lot_consistency(self):
        """Validar consistencia de lotes en desposte"""
        for line in self:
            if line.is_unbuild_line and line.move_id.production_id:
                production = line.move_id.production_id
                # Para el producto principal, el lote debe coincidir
                if (line.product_id == production.product_id and 
                    production.lot_producing_id and 
                    line.lot_id != production.lot_producing_id):
                    raise ValidationError(_(
                        "The lot for the main product must match the unbuild order lot."
                    ))


class StockPicking(models.Model):
    _inherit = 'stock.picking'
    
    # Campo computado para identificar pickings de desposte
    is_unbuild_picking = fields.Boolean(
        string='Is Unbuild Picking',
        compute='_compute_is_unbuild_picking',
        store=True,
        index=True  # Agregado índice
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
                if move.state not in ('done', 'cancel') and float_is_zero(
                    move.quantity, precision_rounding=move.product_uom.rounding
                ):
                    # Para productos de salida, permitir cantidad 0 (desperdicio total)
                    if move.product_id != move.production_id.product_id:
                        continue
                    # Para el producto principal, es obligatorio
                    raise UserError(_(
                        "Input product quantity is required for unbuild order %s"
                    ) % move.production_id.name)
        
        return super().button_validate()


class StockQuant(models.Model):
    _inherit = 'stock.quant'
    
    def _gather(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False):
        """Override para priorizar quants en órdenes de desposte"""
        quants = super()._gather(product_id, location_id, lot_id, package_id, owner_id, strict)
        
        # Si estamos en contexto de desposte, aplicar orden especial
        if self.env.context.get('unbuild_mode'):
            # Para desposte, priorizar:
            # 1. Lotes más antiguos (FIFO)
            # 2. Cantidades más grandes (para minimizar parciales)
            quants = quants.sorted(lambda q: (q.in_date or fields.Datetime.now(), -q.quantity))
        
        return quants
    
    @api.model
    def _update_reserved_quantity(self, product_id, location_id, quantity, lot_id=None, 
                                 package_id=None, owner_id=None, strict=False):
        """Override para manejar reservas en contexto de desposte"""
        # Si estamos en contexto de desposte, aplicar lógica especial
        if self.env.context.get('unbuild_mode') and lot_id:
            # Para desposte con lote específico, forzar uso de ese lote
            return super()._update_reserved_quantity(
                product_id, location_id, quantity, lot_id=lot_id,
                package_id=package_id, owner_id=owner_id, strict=True
            )
        
        return super()._update_reserved_quantity(
            product_id, location_id, quantity, lot_id=lot_id,
            package_id=package_id, owner_id=owner_id, strict=strict
        )