# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Developer: Almus Dev (JDV-ALM) - www.almus.dev

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_round, float_is_zero
from collections import defaultdict


class MrpUnbuild(models.Model):
    """Extensión del modelo de desmantelamiento para centros de desposte"""
    _inherit = 'mrp.unbuild'
    
    state = fields.Selection(
        selection_add=[
            ('ready', 'Listo para Procesar'),
            ('done',)
        ],
        ondelete={'ready': 'set draft'}
    )
    
    unbuild_line_ids = fields.One2many(
        'mrp.unbuild.line',
        'unbuild_id',
        string='Líneas de Desmantelamiento',
        copy=False,
        states={'done': [('readonly', True)]}
    )
    
    show_unbuild_lines = fields.Boolean(
        string='Mostrar Líneas',
        compute='_compute_show_unbuild_lines'
    )
    
    total_expected_qty = fields.Float(
        string='Total Esperado',
        compute='_compute_totals',
        digits='Product Unit of Measure'
    )
    
    total_actual_qty = fields.Float(
        string='Total Real',
        compute='_compute_totals',
        digits='Product Unit of Measure'
    )
    
    total_waste_qty = fields.Float(
        string='Total Desecho',
        compute='_compute_totals',
        digits='Product Unit of Measure'
    )
    
    yield_percentage = fields.Float(
        string='Rendimiento (%)',
        compute='_compute_totals',
        store=True,
        digits=(5, 2),
        help="Porcentaje de producto bueno vs producto inicial"
    )
    
    qty_warning = fields.Char(
        string='Advertencia de Cantidad',
        compute='_compute_qty_warning'
    )
    
    @api.depends('state', 'bom_id')
    def _compute_show_unbuild_lines(self):
        """Determina cuándo mostrar las líneas editables"""
        for unbuild in self:
            unbuild.show_unbuild_lines = unbuild.state in ('ready', 'done')
    
    @api.depends('unbuild_line_ids.expected_qty', 'unbuild_line_ids.actual_qty', 
                 'unbuild_line_ids.is_waste', 'product_qty', 'product_uom_id')
    def _compute_totals(self):
        """Calcula totales y rendimiento"""
        for unbuild in self:
            lines = unbuild.unbuild_line_ids
            unbuild.total_expected_qty = sum(lines.mapped('expected_qty'))
            unbuild.total_actual_qty = sum(lines.mapped('actual_qty'))
            unbuild.total_waste_qty = sum(lines.filtered('is_waste').mapped('actual_qty'))
            
            # Calcular rendimiento (productos buenos / cantidad inicial)
            if unbuild.product_qty > 0:
                good_qty = unbuild.total_actual_qty - unbuild.total_waste_qty
                unbuild.yield_percentage = (good_qty / unbuild.product_qty) * 100
            else:
                unbuild.yield_percentage = 0.0
    
    @api.depends('unbuild_line_ids.actual_qty', 'product_qty', 'product_uom_id')
    def _compute_qty_warning(self):
        """Calcula advertencia si la suma excede la cantidad inicial"""
        for unbuild in self:
            if not unbuild.unbuild_line_ids:
                unbuild.qty_warning = False
                continue
                
            # Convertir todo a la misma UoM para comparación
            total_in_product_uom = sum(
                line.product_uom_id._compute_quantity(line.actual_qty, unbuild.product_uom_id)
                for line in unbuild.unbuild_line_ids
            )
            
            if float_compare(total_in_product_uom, unbuild.product_qty, 
                           precision_rounding=unbuild.product_uom_id.rounding) > 0:
                unbuild.qty_warning = _(
                    '⚠️ La suma de productos (%(total)s %(uom)s) excede la cantidad inicial (%(initial)s %(uom)s)',
                    total=round(total_in_product_uom, 2),
                    initial=unbuild.product_qty,
                    uom=unbuild.product_uom_id.name
                )
            else:
                unbuild.qty_warning = False
    
    def action_prepare_lines(self):
        """Prepara las líneas de desmantelamiento basadas en la BoM"""
        self.ensure_one()
        
        if not self.bom_id:
            raise UserError(_('Debe seleccionar una lista de materiales antes de continuar.'))
        
        # Limpiar líneas existentes
        self.unbuild_line_ids.unlink()
        
        # Calcular factor basado en cantidad
        factor = self.product_uom_id._compute_quantity(
            self.product_qty, 
            self.bom_id.product_uom_id
        ) / self.bom_id.product_qty
        
        # Crear líneas basadas en byproducts de la BoM
        lines_data = []
        sequence = 10
        
        # Si hay byproducts en la BoM, usarlos
        if self.bom_id.byproduct_ids:
            for byproduct in self.bom_id.byproduct_ids:
                if byproduct._skip_byproduct_line(self.product_id):
                    continue
                    
                expected_qty = byproduct.product_qty * factor
                lines_data.append({
                    'sequence': sequence,
                    'product_id': byproduct.product_id.id,
                    'expected_qty': expected_qty,
                    'actual_qty': expected_qty,
                    'product_uom_id': byproduct.product_uom_id.id,
                    'value_factor_bom': byproduct.value_factor if hasattr(byproduct, 'value_factor') else 1.0,
                    'value_factor': byproduct.value_factor if hasattr(byproduct, 'value_factor') else 1.0,
                    'is_waste': False,
                })
                sequence += 10
        else:
            # Si no hay byproducts, crear líneas desde componentes de la BoM
            boms, lines = self.bom_id.explode(self.product_id, factor)
            for bom_line, line_data in lines:
                lines_data.append({
                    'sequence': sequence,
                    'product_id': bom_line.product_id.id,
                    'expected_qty': line_data['qty'],
                    'actual_qty': line_data['qty'],
                    'product_uom_id': bom_line.product_uom_id.id,
                    'value_factor_bom': 1.0,
                    'value_factor': 1.0,
                    'is_waste': False,
                })
                sequence += 10
        
        # Crear las líneas
        for line_data in lines_data:
            self.unbuild_line_ids.create({
                'unbuild_id': self.id,
                **line_data
            })
        
        # Cambiar a estado ready
        self.state = 'ready'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Líneas preparadas'),
                'message': _('Ahora puede ajustar las cantidades reales y marcar productos como desecho.'),
                'type': 'success',
                'sticky': False,
            }
        }
    
    def action_validate_quantities(self):
        """Valida que las cantidades sean correctas antes de procesar"""
        self.ensure_one()
        
        if not self.unbuild_line_ids:
            raise UserError(_('No hay líneas de desmantelamiento para procesar.'))
        
        # Validar que el total de líneas sea igual o menor al producto inicial
        total_in_product_uom = sum(
            line.product_uom_id._compute_quantity(line.actual_qty, self.product_uom_id)
            for line in self.unbuild_line_ids
        )
        
        if float_compare(total_in_product_uom, self.product_qty, 
                        precision_rounding=self.product_uom_id.rounding) > 0:
            raise ValidationError(_(
                'La suma de productos resultantes (%(total)s %(uom)s) no puede ser mayor '
                'que la cantidad inicial (%(initial)s %(uom)s).',
                total=total_in_product_uom,
                initial=self.product_qty,
                uom=self.product_uom_id.name
            ))
        
        # Validar lotes si es necesario
        for line in self.unbuild_line_ids:
            if line.product_id.tracking != 'none' and not line.lot_id:
                raise ValidationError(_(
                    'Debe especificar un lote para el producto %s', 
                    line.product_id.display_name
                ))
        
        return True
    
    def action_unbuild(self):
        """Procesa el desmantelamiento con nuestro proceso personalizado"""
        self.ensure_one()
        
        if self.state == 'ready' and self.unbuild_line_ids:
            # Validar cantidades
            self.action_validate_quantities()
            
            # Usar nuestro proceso personalizado completamente
            return self._custom_unbuild_process()
        else:
            # Comportamiento estándar si no hay líneas
            return super().action_unbuild()
    
    def _custom_unbuild_process(self):
        """Proceso personalizado de desmantelamiento con distribución de costos por factor de valor"""
        self.ensure_one()
        self._check_company()
        
        if self.product_id.tracking != 'none' and not self.lot_id:
            raise UserError(_('Debe proporcionar un lote para el producto final.'))
        
        # Calcular el costo total del producto a desmantelar
        total_cost = self._get_product_total_cost()
        
        # Crear todos los movimientos de una vez
        moves = self.env['stock.move']
        
        # 1. Movimiento de consumo (salida del producto original)
        production_location = self.product_id.with_company(self.company_id).property_stock_production
        consume_move = self.env['stock.move'].create({
            'name': self.name,
            'product_id': self.product_id.id,
            'product_uom_qty': self.product_qty,
            'product_uom': self.product_uom_id.id,
            'location_id': self.location_id.id,
            'location_dest_id': production_location.id,
            'unbuild_id': self.id,
            'company_id': self.company_id.id,
            'origin': self.name,
            'procure_method': 'make_to_stock',
        })
        moves |= consume_move
        
        # 2. Movimientos de producción (entrada de subproductos)
        for line in self.unbuild_line_ids:
            # Determinar ubicación destino
            if line.is_waste:
                scrap_location = self.env['stock.location'].search([
                    ('scrap_location', '=', True),
                    ('company_id', 'in', [self.company_id.id, False])
                ], limit=1)
                if not scrap_location:
                    raise UserError(_('No se encontró ubicación de desecho configurada.'))
                dest_location = scrap_location
            else:
                dest_location = self.location_dest_id
            
            # Calcular el precio unitario basado en la distribución de costos
            if line.is_waste:
                price_unit = 0.0
            else:
                # Usar el cost_share calculado (que ya considera el factor de valor)
                line_cost = total_cost * line.cost_share
                price_unit = line_cost / line.actual_qty if line.actual_qty > 0 else 0.0
            
            produce_move = self.env['stock.move'].create({
                'name': self.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.actual_qty,
                'product_uom': line.product_uom_id.id,
                'location_id': production_location.id,
                'location_dest_id': dest_location.id,
                'consume_unbuild_id': self.id,
                'company_id': self.company_id.id,
                'origin': self.name,
                'procure_method': 'make_to_stock',
                'price_unit': price_unit,  # IMPORTANTE: Establecer el precio unitario
            })
            moves |= produce_move
        
        # 3. Confirmar todos los movimientos
        moves._action_confirm()
        
        # 4. Asignar cantidad a los movimientos
        for move in moves:
            if move == consume_move:
                # Para el movimiento de consumo
                if self.lot_id:
                    self.env['stock.move.line'].create({
                        'move_id': move.id,
                        'lot_id': self.lot_id.id,
                        'quantity': move.product_uom_qty,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                    })
                else:
                    move.quantity = move.product_uom_qty
            else:
                # Para los movimientos de producción
                line = self.unbuild_line_ids.filtered(lambda l: l.product_id == move.product_id)
                if line and line.lot_id:
                    self.env['stock.move.line'].create({
                        'move_id': move.id,
                        'lot_id': line.lot_id.id,
                        'quantity': move.product_uom_qty,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                    })
                else:
                    move.quantity = move.product_uom_qty
        
        # 5. Marcar como picked
        moves.picked = True
        
        # 6. Procesar movimientos
        # Procesar primero el movimiento de consumo
        consume_move._action_done()
        
        # Procesar los movimientos de producción
        for move in moves - consume_move:
            move._action_done()
        
        # 7. Actualizar estado
        self.state = 'done'
        
        # 8. Publicar mensaje
        self._post_inventory_message()
        
        return True
    
    def _get_product_total_cost(self):
        """Obtiene el costo total del producto a desmantelar"""
        self.ensure_one()
        
        if self.product_id.cost_method == 'standard':
            unit_cost = self.product_id.standard_price
        else:
            # Para FIFO/Average, obtener el costo real actual
            product = self.product_id.with_company(self.company_id)
            quantity_svl = product.quantity_svl
            value_svl = product.value_svl
            if quantity_svl > 0:
                unit_cost = value_svl / quantity_svl
            else:
                unit_cost = product.standard_price
        
        return unit_cost * self.product_qty
    
    def _post_inventory_message(self):
        """Publica mensaje con resumen del desmantelamiento"""
        message_body = _(
            "<b>Desmantelamiento completado:</b><br/>"
            "Producto: %(product)s - %(qty)s %(uom)s<br/>"
            "<b>Resultados:</b><br/>",
            product=self.product_id.display_name,
            qty=self.product_qty,
            uom=self.product_uom_id.name
        )
        
        # Agregar detalles de productos buenos
        good_lines = self.unbuild_line_ids.filtered(lambda l: not l.is_waste)
        if good_lines:
            message_body += _("<u>Productos:</u><br/>")
            for line in good_lines:
                # Obtener el costo total del producto
                total_cost = self._get_product_total_cost()
                line_cost = total_cost * line.cost_share
                
                message_body += _("- %(product)s: %(qty)s %(uom)s (Costo: %(cost)s Bs.D - %(percent).1f%%)<br/>",
                    product=line.product_id.display_name,
                    qty=line.actual_qty,
                    uom=line.product_uom_id.name,
                    cost=round(line_cost, 2),
                    percent=line.cost_share * 100
                )
        
        # Agregar detalles de desechos
        waste_lines = self.unbuild_line_ids.filtered('is_waste')
        if waste_lines:
            message_body += _("<u>Desechos:</u><br/>")
            for line in waste_lines:
                message_body += _("- %(product)s: %(qty)s %(uom)s<br/>",
                    product=line.product_id.display_name,
                    qty=line.actual_qty,
                    uom=line.product_uom_id.name
                )
        
        # Agregar rendimiento
        message_body += _("<br/><b>Rendimiento: %(yield_pct).1f%%</b>",
            yield_pct=self.yield_percentage
        )
        
        self.message_post(body=message_body)
    
    @api.model
    def create(self, vals):
        """Asegurar secuencia correcta al crear"""
        unbuild = super().create(vals)
        return unbuild
    
    def unlink(self):
        """Prevenir eliminación en estado ready o done"""
        if any(unbuild.state in ('ready', 'done') for unbuild in self):
            raise UserError(_('No se puede eliminar una orden en estado Listo o Realizado.'))
        return super().unlink()


class StockMove(models.Model):
    """Extensión para controlar la valoración en unbuild personalizado"""
    _inherit = 'stock.move'
    
    def _create_out_svl(self, forced_quantity=None):
        """Sobrescribe para evitar crear diferencias en unbuild personalizado"""
        # Primero crear las SVL normalmente
        svls = super()._create_out_svl(forced_quantity)
        
        # Si hay unbuild con líneas personalizadas, NO crear corrección de costos
        unbuild_svls = svls.filtered('stock_move_id.unbuild_id')
        
        # Filtrar solo los unbuild que NO tienen líneas personalizadas
        # (mantener comportamiento estándar para unbuild normales)
        unbuild_svls_to_correct = unbuild_svls.filtered(
            lambda svl: not svl.stock_move_id.unbuild_id.unbuild_line_ids
        )
        
        if not unbuild_svls_to_correct:
            # Si todos los unbuild tienen líneas personalizadas, no crear corrección
            return svls
        
        # Para unbuild normales (sin líneas personalizadas), mantener lógica estándar
        unbuild_cost_correction_move_list = []
        for svl in unbuild_svls_to_correct:
            # Verificar que existe un MO asociado
            if not svl.stock_move_id.unbuild_id.mo_id:
                continue
                
            build_time_unit_cost = svl.stock_move_id.unbuild_id.mo_id.move_finished_ids.filtered(
                lambda m: m.product_id == svl.product_id
            ).stock_valuation_layer_ids.unit_cost
            
            unbuild_difference = svl.unit_cost - build_time_unit_cost
            
            if svl.product_id.valuation == 'real_time' and not svl.currency_id.is_zero(unbuild_difference):
                product_accounts = svl.product_id.product_tmpl_id.get_product_accounts()
                valuation_account = product_accounts.get('stock_valuation')
                production_account = product_accounts.get('production')
                
                if not valuation_account or not production_account:
                    continue
                
                desc = _('%s - Unbuild Cost Difference', svl.stock_move_id.unbuild_id.name)
                unbuild_cost_correction_move_list.append({
                    'journal_id': product_accounts['stock_journal'].id,
                    'date': fields.Date.context_today(self),
                    'ref': desc,
                    'move_type': 'entry',
                    'line_ids': [(0, 0, {
                        'name': desc,
                        'account_id': valuation_account.id,
                        'debit': unbuild_difference if unbuild_difference > 0 else 0,
                        'credit': -unbuild_difference if unbuild_difference < 0 else 0,
                        'product_id': svl.product_id.id,
                    }), (0, 0, {
                        'name': desc,
                        'account_id': production_account.id,
                        'debit': -unbuild_difference if unbuild_difference < 0 else 0,
                        'credit': unbuild_difference if unbuild_difference > 0 else 0,
                        'product_id': svl.product_id.id,
                    })],
                })
        
        if unbuild_cost_correction_move_list:
            unbuild_cost_correction_moves = self.env['account.move'].sudo().create(unbuild_cost_correction_move_list)
            unbuild_cost_correction_moves._post()
        
        return svls
    
    def _create_in_svl(self, forced_quantity=None):
        """Controla la creación de SVL para movimientos de entrada en unbuild"""
        # Si es un movimiento de producción de unbuild con price_unit establecido
        if self.consume_unbuild_id and self.consume_unbuild_id.unbuild_line_ids and self.price_unit:
            # Si ya tiene SVL, no crear más
            if self.stock_valuation_layer_ids:
                return self.env['stock.valuation.layer']
                
            # Crear SVL con el precio que establecimos
            svl_vals_list = []
            for move in self:
                move = move.with_company(move.company_id)
                valued_move_lines = move._get_in_move_lines()
                valued_quantity = sum(valued_move_lines.mapped("quantity_product_uom"))
                if float_is_zero(forced_quantity or valued_quantity, precision_rounding=move.product_id.uom_id.rounding):
                    continue
                
                quantity = forced_quantity or valued_quantity
                # Usar el price_unit que establecimos
                unit_cost = move.price_unit
                
                svl_vals = {
                    'product_id': move.product_id.id,
                    'value': quantity * unit_cost,
                    'unit_cost': unit_cost,
                    'quantity': quantity,
                    'remaining_qty': quantity,
                    'remaining_value': quantity * unit_cost,
                    'stock_move_id': move.id,
                    'company_id': move.company_id.id,
                    'description': move.reference and '%s - %s' % (move.reference, move.product_id.name) or move.product_id.name,
                }
                svl_vals_list.append(svl_vals)
            
            return self.env['stock.valuation.layer'].sudo().create(svl_vals_list)
        else:
            return super()._create_in_svl(forced_quantity)
    
    def _create_in_svl(self, forced_quantity=None):
        """Controla la creación de SVL para movimientos de entrada en unbuild"""
        # Si es un movimiento de producción de unbuild con price_unit establecido
        if self.consume_unbuild_id and self.consume_unbuild_id.unbuild_line_ids and self.price_unit:
            # Crear SVL con el precio que establecimos
            svl_vals_list = []
            for move in self:
                move = move.with_company(move.company_id)
                valued_move_lines = move._get_in_move_lines()
                valued_quantity = sum(valued_move_lines.mapped("quantity_product_uom"))
                if float_is_zero(forced_quantity or valued_quantity, precision_rounding=move.product_id.uom_id.rounding):
                    continue
                
                quantity = forced_quantity or valued_quantity
                # Usar el price_unit que establecimos
                unit_cost = move.price_unit
                
                svl_vals = {
                    'product_id': move.product_id.id,
                    'value': quantity * unit_cost,
                    'unit_cost': unit_cost,
                    'quantity': quantity,
                    'remaining_qty': quantity,
                    'remaining_value': quantity * unit_cost,
                    'stock_move_id': move.id,
                    'company_id': move.company_id.id,
                    'description': move.reference and '%s - %s' % (move.reference, move.product_id.name) or move.product_id.name,
                }
                svl_vals_list.append(svl_vals)
            
            return self.env['stock.valuation.layer'].sudo().create(svl_vals_list)
        else:
            return super()._create_in_svl(forced_quantity)