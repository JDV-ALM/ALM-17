# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_round, float_is_zero


class MrpProduction(models.Model):
    _inherit = 'mrp.production'
    
    # Campo computado para identificar órdenes de desposte
    is_unbuild_order = fields.Boolean(
        string='Is Unbuild Order',
        compute='_compute_is_unbuild_order',
        store=True,
        index=True  # Agregado índice para mejor performance
    )
    
    # Campos específicos para desposte
    unbuild_yield_line_ids = fields.One2many(
        'mrp.production.unbuild.yield',
        'production_id',
        string='Actual Yields',
        readonly=False,
        states={'done': [('readonly', True)], 'cancel': [('readonly', True)]}
    )
    
    # Override para cambiar el dominio del bom_id según el contexto
    bom_id = fields.Many2one(
        domain="""[
        '&',
            '|',
                ('company_id', '=', False),
                ('company_id', '=', company_id),
            '&',
                '|',
                    ('product_id','=',product_id),
                    '&',
                        ('product_tmpl_id.product_variant_ids','=',product_id),
                        ('product_id','=',False),
        ('type', '=', is_unbuild_order and 'unbuild' or 'normal')]"""
    )
    
    # Campos para análisis de rendimiento en desposte
    unbuild_efficiency = fields.Float(
        string='Unbuild Efficiency %',
        compute='_compute_unbuild_efficiency',
        store=True,
        help="Efficiency of the unbuild process compared to expected yields"
    )
    
    total_waste_qty = fields.Float(
        string='Total Waste',
        compute='_compute_waste_qty',
        store=True
    )
    
    # Campo para validar disponibilidad
    has_sufficient_stock = fields.Boolean(
        string='Has Sufficient Stock',
        compute='_compute_has_sufficient_stock',
        help="Indicates if there's enough stock to perform the unbuild"
    )
    
    # Campo para total de costo asignado
    total_cost_allocation = fields.Float(
        string='Total Cost Allocation %',
        compute='_compute_total_cost_allocation',
        store=True,
        help="Total percentage of cost allocated to output products"
    )
    
    @api.depends('bom_id', 'bom_id.type')
    def _compute_is_unbuild_order(self):
        for production in self:
            production.is_unbuild_order = production.bom_id and production.bom_id.type == 'unbuild'
    
    @api.depends('unbuild_yield_line_ids.actual_qty', 'unbuild_yield_line_ids.expected_qty')
    def _compute_unbuild_efficiency(self):
        for production in self:
            if not production.is_unbuild_order or not production.unbuild_yield_line_ids:
                production.unbuild_efficiency = 0
                continue
            
            total_expected = sum(production.unbuild_yield_line_ids.mapped('expected_qty'))
            total_actual = sum(production.unbuild_yield_line_ids.mapped('actual_qty'))
            
            if total_expected:
                production.unbuild_efficiency = (total_actual / total_expected) * 100
            else:
                production.unbuild_efficiency = 0
    
    @api.depends('unbuild_yield_line_ids.actual_qty', 'unbuild_yield_line_ids.is_waste')
    def _compute_waste_qty(self):
        for production in self:
            if production.is_unbuild_order:
                waste_lines = production.unbuild_yield_line_ids.filtered('is_waste')
                production.total_waste_qty = sum(waste_lines.mapped('actual_qty'))
            else:
                production.total_waste_qty = 0
    
    @api.depends('product_id', 'product_qty', 'location_src_id')
    def _compute_has_sufficient_stock(self):
        for production in self:
            if not production.is_unbuild_order or not production.product_id:
                production.has_sufficient_stock = True
                continue
            
            # Verificar disponibilidad de stock
            available_qty = production.env['stock.quant']._get_available_quantity(
                production.product_id,
                production.location_src_id,
                lot_id=production.lot_producing_id,
                strict=True
            )
            
            production.has_sufficient_stock = float_compare(
                available_qty,
                production.product_qty,
                precision_rounding=production.product_uom_id.rounding
            ) >= 0
    
    @api.depends('unbuild_yield_line_ids.cost_share', 'unbuild_yield_line_ids.is_waste')
    def _compute_total_cost_allocation(self):
        for production in self:
            if production.is_unbuild_order:
                non_waste_lines = production.unbuild_yield_line_ids.filtered(lambda l: not l.is_waste)
                production.total_cost_allocation = sum(non_waste_lines.mapped('cost_share'))
            else:
                production.total_cost_allocation = 0
    
    @api.onchange('bom_id')
    def _onchange_bom_id_unbuild(self):
        """Populate yield lines when selecting an unbuild BoM"""
        if self.is_unbuild_order and self.bom_id and self.bom_id.unbuild_yield_ids:
            yield_lines = []
            for yield_data in self.bom_id.unbuild_yield_ids:
                yield_lines.append(Command.create({
                    'product_id': yield_data.product_id.id,
                    'expected_qty': yield_data.expected_qty * self.product_qty,
                    'product_uom_id': yield_data.product_uom_id.id,
                    'cost_share': yield_data.cost_share,
                    'is_waste': yield_data.is_waste,
                }))
            self.unbuild_yield_line_ids = yield_lines
    
    @api.onchange('product_qty')
    def _onchange_product_qty_unbuild(self):
        """Update expected quantities when changing the quantity to unbuild"""
        if self.is_unbuild_order and self.bom_id and self.unbuild_yield_line_ids:
            for line in self.unbuild_yield_line_ids:
                bom_yield = self.bom_id.unbuild_yield_ids.filtered(
                    lambda y: y.product_id == line.product_id
                )
                if bom_yield:
                    line.expected_qty = bom_yield.expected_qty * self.product_qty
    
    def _get_moves_raw_values(self):
        """Override para manejar desposte - en desposte no hay materias primas"""
        if self.is_unbuild_order:
            return []
        return super()._get_moves_raw_values()
    
    def _get_moves_finished_values(self):
        """Override para manejar productos terminados en desposte"""
        if not self.is_unbuild_order:
            return super()._get_moves_finished_values()
        
        moves = []
        # En desposte, el producto principal es consumido (movimiento negativo)
        moves.append(self._get_unbuild_consume_move_values())
        
        # Los subproductos son producidos
        for line in self.bom_id.bom_line_ids:
            if line._skip_bom_line(self.product_id):
                continue
            
            factor = self.product_uom_id._compute_quantity(
                self.product_qty, self.bom_id.product_uom_id
            ) / self.bom_id.product_qty
            
            qty = line.product_qty * factor
            move_values = self._get_move_finished_values(
                line.product_id.id,
                qty,
                line.product_uom_id.id,
                operation_id=line.operation_id.id,
                byproduct_id=False,
                cost_share=0
            )
            # Invertir origen y destino para desposte
            move_values.update({
                'location_id': self.location_dest_id.id,
                'location_dest_id': self.production_location_id.id,
                'is_unbuild_move': True,
            })
            moves.append(move_values)
        
        return moves
    
    def _get_unbuild_consume_move_values(self):
        """Crear movimiento de consumo del producto a despiezar"""
        return {
            'name': _('Unbuild: %s', self.name),
            'product_id': self.product_id.id,
            'product_uom_qty': self.product_qty,
            'product_uom': self.product_uom_id.id,
            'location_id': self.location_src_id.id,
            'location_dest_id': self.production_location_id.id,
            'company_id': self.company_id.id,
            'production_id': self.id,
            'warehouse_id': self.location_src_id.warehouse_id.id,
            'origin': self.name,
            'group_id': self.procurement_group_id.id,
            'date': self.date_start,
            'date_deadline': self.date_start,
            'propagate_cancel': self.propagate_cancel,
            'picking_type_id': self.picking_type_id.id,
            'is_unbuild_move': True,
        }
    
    def action_confirm(self):
        """Override para validar órdenes de desposte"""
        unbuild_orders = self.filtered('is_unbuild_order')
        for order in unbuild_orders:
            if not order.bom_id:
                raise UserError(_("Please select an Unbuild BoM before confirming."))
            if order.product_qty <= 0:
                raise UserError(_("The quantity to unbuild must be positive."))
            
            # Validar disponibilidad de stock
            if not order.has_sufficient_stock:
                raise UserError(_(
                    "Insufficient stock for product %s.\n"
                    "Required: %s %s\n"
                    "Available: %s %s"
                ) % (
                    order.product_id.display_name,
                    order.product_qty,
                    order.product_uom_id.name,
                    order.env['stock.quant']._get_available_quantity(
                        order.product_id,
                        order.location_src_id,
                        lot_id=order.lot_producing_id,
                        strict=True
                    ),
                    order.product_uom_id.name
                ))
            
            # Validar asignación de costos si está configurado
            if self.env['ir.config_parameter'].sudo().get_param('mrp.unbuild.strict_cost_allocation'):
                if float_compare(order.total_cost_allocation, 100, precision_digits=2) != 0:
                    raise UserError(_(
                        "Cost allocation must be exactly 100%%. Current allocation: %s%%"
                    ) % order.total_cost_allocation)
        
        return super().action_confirm()
    
    def _cal_price(self, consumed_moves):
        """Override para calcular costos en desposte"""
        if not self.is_unbuild_order:
            return super()._cal_price(consumed_moves)
        
        # En desposte, distribuir el costo del producto consumido entre los subproductos
        main_move = self.move_finished_ids.filtered(
            lambda m: m.product_id == self.product_id
        )
        if not main_move:
            return True
        
        total_cost = abs(sum(main_move.stock_valuation_layer_ids.mapped('value'))) if main_move.stock_valuation_layer_ids else 0
        
        # Calcular costo no asignado
        unallocated_percentage = 100 - self.total_cost_allocation
        if unallocated_percentage > 0:
            # Registrar costo no asignado en cuenta de pérdidas
            self._create_unbuild_loss_entry(total_cost * unallocated_percentage / 100)
        
        # Distribuir costo según cost_share definido
        for yield_line in self.unbuild_yield_line_ids.filtered(lambda l: not l.is_waste):
            if yield_line.cost_share <= 0:
                continue
            
            output_move = self.move_finished_ids.filtered(
                lambda m: m.product_id == yield_line.product_id and m.id != main_move.id
            )
            if output_move and output_move.product_id.cost_method in ('fifo', 'average'):
                allocated_cost = total_cost * yield_line.cost_share / 100
                output_move.price_unit = allocated_cost / output_move.product_qty if output_move.product_qty else 0
        
        return True
    
    def _create_unbuild_loss_entry(self, loss_amount):
        """Crear asiento contable para pérdidas no asignadas"""
        if float_is_zero(loss_amount, precision_rounding=self.company_id.currency_id.rounding):
            return
        
        # Obtener cuenta de pérdidas
        loss_account_id = self.env['ir.config_parameter'].sudo().get_param(
            'mrp.unbuild.loss_account_id.%s' % self.company_id.id
        )
        if not loss_account_id:
            # Si no hay cuenta configurada, usar cuenta de ajuste de inventario
            loss_account = self.location_dest_id.valuation_out_account_id
        else:
            loss_account = self.env['account.account'].browse(int(loss_account_id))
        
        # Crear línea analítica si aplica
        if self.analytic_distribution and loss_account:
            self.env['account.analytic.line'].create({
                'name': _('Unbuild Loss: %s') % self.name,
                'amount': loss_amount,
                'account_id': self.analytic_account_id.id,
                'ref': self.name,
                'company_id': self.company_id.id,
            })
    
    def button_mark_done(self):
        """Override para capturar rendimientos reales antes de procesar"""
        for production in self.filtered('is_unbuild_order'):
            # Validar que se hayan capturado rendimientos
            if not production.unbuild_yield_line_ids:
                raise UserError(_("Please capture actual yields before marking as done."))
            
            # Validar tolerancia de rendimientos si está configurado
            tolerance = float(self.env['ir.config_parameter'].sudo().get_param(
                'mrp.unbuild.yield_tolerance', default='5.0'
            ))
            
            for yield_line in production.unbuild_yield_line_ids:
                if yield_line.expected_qty > 0 and abs(yield_line.variance_percent) > tolerance:
                    # Solo advertencia, no error
                    production.message_post(
                        body=_(
                            "Yield variance for %s exceeds tolerance: %.2f%% (tolerance: %.2f%%)"
                        ) % (yield_line.product_id.display_name, yield_line.variance_percent, tolerance)
                    )
                
                # Actualizar cantidades en movimientos según rendimientos reales
                move = production.move_finished_ids.filtered(
                    lambda m: m.product_id == yield_line.product_id and m.product_id != production.product_id
                )
                if move and move.state not in ('done', 'cancel'):
                    move.product_uom_qty = yield_line.actual_qty
        
        return super().button_mark_done()
    
    def action_view_stock_valuation_layers(self):
        """Extender para mostrar valoración específica de desposte"""
        action = super().action_view_stock_valuation_layers()
        if self.is_unbuild_order:
            action['name'] = _('Unbuild Order Valuation')
            # Agregar contexto para identificar vista de desposte
            action['context'] = dict(action.get('context', {}), unbuild_mode=True)
        return action
    
    @api.model
    def _get_name_backorder(self, name, sequence):
        if self.is_unbuild_order:
            # Usar prefijo diferente para backorders de desposte
            return name.replace('UO', 'UO-BACK') + '-%d' % sequence
        return super()._get_name_backorder(name, sequence)


class MrpProductionUnbuildYield(models.Model):
    """Captura de rendimientos reales en órdenes de desposte"""
    _name = 'mrp.production.unbuild.yield'
    _description = 'Unbuild Production Yields'
    _order = 'sequence, id'
    
    production_id = fields.Many2one(
        'mrp.production',
        string='Production Order',
        required=True,
        ondelete='cascade',
        domain=[('is_unbuild_order', '=', True)]
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True
    )
    
    sequence = fields.Integer(
        string='Sequence',
        default=10
    )
    
    expected_qty = fields.Float(
        string='Expected Qty',
        required=True,
        readonly=True
    )
    
    actual_qty = fields.Float(
        string='Actual Qty',
        required=True,
        default=0.0
    )
    
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        required=True
    )
    
    variance = fields.Float(
        string='Variance',
        compute='_compute_variance',
        store=True
    )
    
    variance_percent = fields.Float(
        string='Variance %',
        compute='_compute_variance',
        store=True
    )
    
    cost_share = fields.Float(
        string='Cost Share %',
        readonly=True
    )
    
    is_waste = fields.Boolean(
        string='Is Waste',
        readonly=True
    )
    
    state = fields.Selection(
        related='production_id.state',
        string='State',
        readonly=True
    )
    
    @api.depends('expected_qty', 'actual_qty')
    def _compute_variance(self):
        for line in self:
            line.variance = line.actual_qty - line.expected_qty
            if line.expected_qty:
                line.variance_percent = (line.variance / line.expected_qty) * 100
            else:
                line.variance_percent = 0
    
    @api.constrains('actual_qty')
    def _check_actual_qty(self):
        for line in self:
            if line.actual_qty < 0:
                raise ValidationError(_("Actual quantity cannot be negative."))
    
    def action_apply_expected(self):
        """Acción para aplicar cantidades esperadas como reales"""
        for line in self:
            if line.state not in ('done', 'cancel'):
                line.actual_qty = line.expected_qty