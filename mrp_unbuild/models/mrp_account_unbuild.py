# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.tools import float_round, float_is_zero
from odoo.exceptions import UserError


class MrpProductionUnbuildAccount(models.Model):
    _inherit = 'mrp.production'
    
    # Campos adicionales para análisis de costos en desposte
    unbuild_total_cost = fields.Monetary(
        string='Total Input Cost',
        compute='_compute_unbuild_costs',
        store=True,
        currency_field='currency_id'
    )
    
    unbuild_allocated_cost = fields.Monetary(
        string='Allocated Cost',
        compute='_compute_unbuild_costs',
        store=True,
        currency_field='currency_id'
    )
    
    unbuild_waste_cost = fields.Monetary(
        string='Waste Cost',
        compute='_compute_unbuild_costs',
        store=True,
        currency_field='currency_id'
    )
    
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        string='Currency',
        readonly=True
    )
    
    @api.depends('move_finished_ids.stock_valuation_layer_ids.value', 
                 'unbuild_yield_line_ids.cost_share',
                 'unbuild_yield_line_ids.is_waste',
                 'state')
    def _compute_unbuild_costs(self):
        for production in self:
            if not production.is_unbuild_order:
                production.unbuild_total_cost = 0
                production.unbuild_allocated_cost = 0
                production.unbuild_waste_cost = 0
                continue
            
            # Costo total del producto de entrada
            input_move = production.move_finished_ids.filtered(
                lambda m: m.product_id == production.product_id
            )
            if input_move and input_move.stock_valuation_layer_ids:
                production.unbuild_total_cost = abs(sum(input_move.stock_valuation_layer_ids.mapped('value')))
            else:
                production.unbuild_total_cost = 0
            
            # Costo asignado a productos (no waste)
            allocated = 0
            for yield_line in production.unbuild_yield_line_ids.filtered(lambda l: not l.is_waste):
                allocated += production.unbuild_total_cost * yield_line.cost_share / 100
            production.unbuild_allocated_cost = allocated
            
            # Costo de desperdicios
            production.unbuild_waste_cost = production.unbuild_total_cost - allocated
    
    def _cal_price(self, consumed_moves):
        """Override para calcular precios en desposte"""
        if not self.is_unbuild_order:
            return super()._cal_price(consumed_moves)
        
        self.ensure_one()
        
        # Obtener el movimiento principal (entrada)
        main_move = self.move_finished_ids.filtered(
            lambda m: m.product_id == self.product_id and m.state not in ('done', 'cancel')
        )
        if not main_move:
            return True
        
        # Calcular costo total incluyendo work center costs si aplica
        work_center_cost = 0
        for work_order in self.workorder_ids:
            work_center_cost += work_order._cal_cost()
        
        # Costo base del producto + extra costs + work center
        input_cost = abs(sum(consumed_moves.stock_valuation_layer_ids.mapped('value')))
        extra_cost = self.extra_cost * self.qty_producing
        total_cost = input_cost + work_center_cost + extra_cost
        
        # Distribuir costos según configuración
        self._distribute_unbuild_costs(total_cost)
        
        return True
    
    def _distribute_unbuild_costs(self, total_cost):
        """Distribuir costos entre productos de salida según cost_share"""
        self.ensure_one()
        
        if not self.is_unbuild_order:
            return
        
        # Verificar que la suma de cost_share no exceda 100%
        total_share = sum(self.unbuild_yield_line_ids.filtered(lambda l: not l.is_waste).mapped('cost_share'))
        if total_share > 100:
            raise UserError(_("Total cost share exceeds 100%%. Please check yield configuration."))
        
        # Distribuir costos a cada producto de salida
        for yield_line in self.unbuild_yield_line_ids:
            if yield_line.is_waste:
                # Los desperdicios no reciben costo
                continue
            
            output_move = self.move_finished_ids.filtered(
                lambda m: m.product_id == yield_line.product_id 
                and m.state not in ('done', 'cancel')
                and m.product_id != self.product_id
            )
            
            if not output_move:
                continue
            
            # Calcular costo asignado
            if yield_line.cost_share > 0:
                allocated_cost = total_cost * yield_line.cost_share / 100
                
                # Calcular precio unitario
                qty = output_move.product_uom._compute_quantity(
                    output_move.quantity or output_move.product_uom_qty,
                    output_move.product_id.uom_id
                )
                
                if not float_is_zero(qty, precision_rounding=output_move.product_id.uom_id.rounding):
                    if output_move.product_id.cost_method in ('fifo', 'average'):
                        output_move.price_unit = allocated_cost / qty
                    
                    # Crear entrada analítica si aplica
                    if self.analytic_distribution:
                        self._create_unbuild_analytic_entry(output_move, allocated_cost)
    
    def _create_unbuild_analytic_entry(self, move, cost):
        """Crear entrada analítica para movimiento de desposte"""
        if not self.analytic_distribution or not cost:
            return
        
        # Crear línea analítica
        vals = {
            'name': _('Unbuild: %s - %s') % (self.name, move.product_id.display_name),
            'amount': -cost,  # Negativo porque es un ingreso de producto
            'account_id': self.analytic_account_id.id,
            'product_id': move.product_id.id,
            'product_uom_id': move.product_uom.id,
            'unit_amount': move.quantity,
            'ref': self.name,
        }
        
        self.env['account.analytic.line'].sudo().create(vals)
    
    def button_mark_done(self):
        """Override para validaciones de costo antes de finalizar"""
        for production in self.filtered('is_unbuild_order'):
            # Verificar que se haya asignado todo el costo
            total_share = sum(production.unbuild_yield_line_ids.filtered(
                lambda l: not l.is_waste
            ).mapped('cost_share'))
            
            if float_compare(total_share, 100, precision_digits=2) != 0:
                # Advertencia, no error estricto
                production.message_post(
                    body=_("Warning: Total cost allocation is %s%%. Unallocated costs will be treated as loss.") % total_share
                )
        
        return super().button_mark_done()


class MrpProductionUnbuildYieldAccount(models.Model):
    _inherit = 'mrp.production.unbuild.yield'
    
    # Campos adicionales para análisis de costos
    allocated_cost = fields.Monetary(
        string='Allocated Cost',
        compute='_compute_allocated_cost',
        store=True,
        currency_field='currency_id'
    )
    
    unit_cost = fields.Monetary(
        string='Unit Cost',
        compute='_compute_allocated_cost',
        store=True,
        currency_field='currency_id'
    )
    
    currency_id = fields.Many2one(
        related='production_id.company_id.currency_id',
        string='Currency',
        readonly=True
    )
    
    @api.depends('cost_share', 'production_id.unbuild_total_cost', 'actual_qty')
    def _compute_allocated_cost(self):
        for line in self:
            if line.is_waste or not line.cost_share:
                line.allocated_cost = 0
                line.unit_cost = 0
                continue
            
            # Costo asignado = costo total * porcentaje
            line.allocated_cost = line.production_id.unbuild_total_cost * line.cost_share / 100
            
            # Costo unitario
            if line.actual_qty > 0:
                line.unit_cost = line.allocated_cost / line.actual_qty
            else:
                line.unit_cost = 0


class StockMoveUnbuildAccount(models.Model):
    _inherit = 'stock.move'
    
    def _prepare_account_move_vals(self, credit_account_id, debit_account_id, journal_id, qty, description, svl_id, cost):
        """Override para manejar asientos contables de desposte"""
        vals = super()._prepare_account_move_vals(
            credit_account_id, debit_account_id, journal_id, qty, description, svl_id, cost
        )
        
        if self.is_unbuild_move and self.production_id and self.production_id.is_unbuild_order:
            # Personalizar descripción para movimientos de desposte
            vals['ref'] = _('Unbuild: %s') % self.production_id.name
            
            # Agregar distribución analítica si aplica
            if self.production_id.analytic_distribution:
                for line in vals.get('line_ids', []):
                    line[2]['analytic_distribution'] = self.production_id.analytic_distribution
        
        return vals
    
    def _generate_valuation_lines_data(self, partner_id, qty, debit_value, credit_value, debit_account_id, credit_account_id, svl_id, description):
        """Override para asientos contables de desposte"""
        rslt = super()._generate_valuation_lines_data(
            partner_id, qty, debit_value, credit_value, 
            debit_account_id, credit_account_id, svl_id, description
        )
        
        if self.is_unbuild_move and self.production_id and self.production_id.is_unbuild_order:
            # Agregar información adicional para trazabilidad
            for line_vals in rslt.values():
                if line_vals.get('product_id') == self.product_id.id:
                    line_vals['name'] = _('Unbuild: %(prod)s - %(ref)s', 
                                        prod=self.product_id.display_name,
                                        ref=self.production_id.name)
        
        return rslt


class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    def _compute_bom_price(self, bom, boms_to_recompute=False, byproduct_bom=False):
        """Override para excluir BOMs de tipo unbuild del cálculo de costo"""
        if bom and bom.type == 'unbuild':
            # Los BOMs de desposte no se usan para calcular costo estándar
            return 0
        
        return super()._compute_bom_price(bom, boms_to_recompute, byproduct_bom)