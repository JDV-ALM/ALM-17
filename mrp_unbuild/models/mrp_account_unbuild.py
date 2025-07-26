# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.tools import float_round, float_is_zero, float_compare
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
    
    unbuild_unallocated_cost = fields.Monetary(
        string='Unallocated Cost',
        compute='_compute_unbuild_costs',
        store=True,
        currency_field='currency_id',
        help="Cost not assigned to any output product"
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
                production.unbuild_unallocated_cost = 0
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
            
            # Costo de desperdicios (productos marcados como waste)
            waste_cost = 0
            for yield_line in production.unbuild_yield_line_ids.filtered('is_waste'):
                # Los desperdicios tienen costo 0 por definición
                waste_cost += 0
            production.unbuild_waste_cost = waste_cost
            
            # Costo no asignado
            production.unbuild_unallocated_cost = production.unbuild_total_cost - production.unbuild_allocated_cost
    
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
        finished_wo = self.workorder_ids.filtered(lambda w: w.state == 'done')
        for work_order in finished_wo:
            work_center_cost += work_order._cal_cost()
        
        # Costo base del producto + extra costs + work center
        input_cost = 0
        if consumed_moves:
            input_cost = abs(sum(consumed_moves.stock_valuation_layer_ids.mapped('value')))
        else:
            # Si no hay consumed_moves, usar el valor del producto
            input_cost = main_move.product_qty * main_move.product_id.standard_price
        
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
        
        # Verificar configuración de asignación estricta
        strict_allocation = self.env['ir.config_parameter'].sudo().get_param(
            'mrp.unbuild.strict_cost_allocation', False
        )
        
        # Calcular total de cost_share
        total_share = sum(self.unbuild_yield_line_ids.filtered(lambda l: not l.is_waste).mapped('cost_share'))
        
        if strict_allocation and float_compare(total_share, 100, precision_digits=2) != 0:
            raise UserError(_(
                "Total cost share must be exactly 100%%. Current total: %s%%"
            ) % total_share)
        
        # Si hay costo no asignado, registrarlo
        if total_share < 100:
            unallocated_percentage = 100 - total_share
            unallocated_cost = total_cost * unallocated_percentage / 100
            
            # Crear movimiento contable para pérdida
            self._create_unbuild_loss_move(unallocated_cost)
        
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
    
    def _create_unbuild_loss_move(self, loss_amount):
        """Crear asiento contable para pérdidas no asignadas"""
        if float_is_zero(loss_amount, precision_rounding=self.company_id.currency_id.rounding):
            return
        
        # Obtener cuenta de pérdidas configurada
        ICP = self.env['ir.config_parameter'].sudo()
        loss_account_id = ICP.get_param(
            'mrp.unbuild.loss_account_id.%s' % self.company_id.id
        )
        
        if not loss_account_id:
            # Buscar cuenta de pérdidas por defecto
            loss_account = self.env['account.account'].search([
                ('code', '=like', '659%'),
                ('account_type', '=', 'expense_direct_cost'),
                ('company_id', '=', self.company_id.id)
            ], limit=1)
            
            if not loss_account:
                # Usar cuenta de ajuste de inventario como fallback
                loss_account = self.location_dest_id.valuation_out_account_id
        else:
            loss_account = self.env['account.account'].browse(int(loss_account_id))
        
        if not loss_account:
            raise UserError(_(
                "No loss account configured for unbuild operations. "
                "Please configure it in Manufacturing settings."
            ))
        
        # Obtener cuenta de inventario
        stock_input_account = self.product_id.categ_id.property_stock_account_input_categ_id
        if not stock_input_account:
            stock_input_account = self.location_dest_id.valuation_in_account_id
        
        # Crear asiento contable
        move_vals = {
            'journal_id': self.company_id.currency_exchange_journal_id.id or 
                         self.env['account.journal'].search([
                             ('type', '=', 'general'),
                             ('company_id', '=', self.company_id.id)
                         ], limit=1).id,
            'date': fields.Date.context_today(self),
            'ref': _('Unbuild Loss: %s') % self.name,
            'company_id': self.company_id.id,
            'line_ids': [
                (0, 0, {
                    'name': _('Unbuild Loss: %s') % self.name,
                    'account_id': loss_account.id,
                    'debit': loss_amount,
                    'credit': 0,
                    'analytic_distribution': self.analytic_distribution,
                }),
                (0, 0, {
                    'name': _('Unbuild Loss: %s') % self.name,
                    'account_id': stock_input_account.id,
                    'debit': 0,
                    'credit': loss_amount,
                }),
            ],
        }
        
        account_move = self.env['account.move'].create(move_vals)
        account_move.action_post()
        
        # Mensaje en el chatter
        self.message_post(
            body=_("Unallocated cost of %s was posted to loss account %s") % (
                loss_amount, loss_account.display_name
            )
        )
    
    def _create_unbuild_analytic_entry(self, move, cost):
        """Crear entrada analítica para movimiento de desposte"""
        if not self.analytic_distribution or not cost:
            return
        
        # Crear línea analítica
        analytic_line_vals = {
            'name': _('Unbuild: %s - %s') % (self.name, move.product_id.display_name),
            'amount': -cost,  # Negativo porque es un ingreso de producto
            'product_id': move.product_id.id,
            'product_uom_id': move.product_uom.id,
            'unit_amount': move.quantity,
            'ref': self.name,
            'company_id': self.company_id.id,
        }
        
        # Distribuir según analytic_distribution
        for account_id, percentage in self.analytic_distribution.items():
            vals = dict(analytic_line_vals)
            vals['account_id'] = int(account_id)
            vals['amount'] = vals['amount'] * percentage / 100
            self.env['account.analytic.line'].sudo().create(vals)
    
    def button_mark_done(self):
        """Override para validaciones de costo antes de finalizar"""
        for production in self.filtered('is_unbuild_order'):
            # Verificar que se haya asignado todo el costo
            total_share = sum(production.unbuild_yield_line_ids.filtered(
                lambda l: not l.is_waste
            ).mapped('cost_share'))
            
            if float_compare(total_share, 100, precision_digits=2) < 0:
                # Advertencia sobre costo no asignado
                production.message_post(
                    body=_(
                        "Warning: Total cost allocation is %s%%. "
                        "Unallocated costs (%s%%) will be posted to loss account."
                    ) % (total_share, 100 - total_share)
                )
        
        return super().button_mark_done()
    
    def action_view_unbuild_costs(self):
        """Acción para ver análisis detallado de costos de desposte"""
        self.ensure_one()
        return {
            'name': _('Unbuild Cost Analysis'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': {
                'form_view_initial_mode': 'readonly',
                'show_cost_analysis': True,
            },
            'views': [(self.env.ref('mrp_unbuild.view_mrp_production_unbuild_cost_analysis').id, 'form')],
        }


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