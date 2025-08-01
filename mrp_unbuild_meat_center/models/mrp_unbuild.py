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
        digits=(5, 2),
        help="Porcentaje de producto bueno vs producto inicial"
    )
    
    # Nuevo campo para advertencia de exceso
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
                unbuild.yield_percentage = good_qty / unbuild.product_qty
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
        
        # Validar método de costeo
        if self.product_id.cost_method == 'standard':
            raise UserError(_(
                'El producto "%s" usa método de costo estándar. '
                'Este módulo requiere método FIFO o Promedio para distribuir costos correctamente.',
                self.product_id.display_name
            ))
        
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
                    'actual_qty': expected_qty,  # Inicializar con valor esperado
                    'product_uom_id': byproduct.product_uom_id.id,
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
                    'value_factor': 1.0,  # Valor por defecto si no hay byproducts
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
        
        # Validar método de costeo nuevamente
        if self.product_id.cost_method == 'standard':
            raise UserError(_(
                'No se puede procesar el desmantelamiento. '
                'El producto usa método de costo estándar que no es compatible con la distribución de costos.'
            ))
        
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
            if line.product_tracking != 'none' and not line.lot_id:
                raise ValidationError(_(
                    'Debe especificar un lote para el producto %s', 
                    line.product_id.display_name
                ))
        
        return True
    
    def action_unbuild(self):
        """Sobrescribe el método original para usar nuestras líneas editables"""
        self.ensure_one()
        
        if self.state == 'ready' and self.unbuild_line_ids:
            # Validar cantidades
            self.action_validate_quantities()
            
            # Procesar con nuestras líneas personalizadas
            return self._process_unbuild_with_lines()
        else:
            # Comportamiento estándar si no hay líneas
            return super().action_unbuild()
    
    def _process_unbuild_with_lines(self):
        """Procesa el desmantelamiento usando las líneas editables"""
        self.ensure_one()
        self._check_company()
        
        if self.product_id.tracking != 'none' and not self.lot_id:
            raise UserError(_('Debe proporcionar un lote para el producto final.'))
        
        # Crear movimiento de consumo (producto original)
        consume_move = self._create_consume_move()
        consume_move._action_confirm()
        
        # Crear movimientos de producción (líneas)
        produce_moves = self._create_produce_moves_from_lines()
        produce_moves._action_confirm()
        
        # Preparar líneas de movimiento
        self._prepare_move_lines(consume_move, produce_moves)
        
        # Marcar como realizado
        consume_move.picked = True
        produce_moves.picked = True
        
        # Procesar movimientos
        consume_move._action_done()
        produce_moves._action_done()
        
        # Ajustar valoración si mrp_account está instalado
        if hasattr(self, '_adjust_cost_valuation'):
            self._adjust_cost_valuation(consume_move, produce_moves)
        
        # Actualizar estado
        self.state = 'done'
        
        # Mensaje de confirmación
        self._post_inventory_message()
        
        return True
    
    def _create_consume_move(self):
        """Crea el movimiento de consumo del producto original"""
        self.ensure_one()
        
        return self.env['stock.move'].create({
            'name': self.name,
            'product_id': self.product_id.id,
            'product_uom_qty': self.product_qty,
            'product_uom': self.product_uom_id.id,
            'location_id': self.location_id.id,
            'location_dest_id': self.product_id.with_company(self.company_id).property_stock_production.id,
            'unbuild_id': self.id,
            'company_id': self.company_id.id,
            'origin': self.name,
        })
    
    def _create_produce_moves_from_lines(self):
        """Crea movimientos de producción desde las líneas editables"""
        self.ensure_one()
        
        moves = self.env['stock.move']
        production_location = self.product_id.with_company(self.company_id).property_stock_production
        
        # Calcular el costo total del producto original
        total_cost = 0.0
        if self.product_id.cost_method in ('fifo', 'average'):
            # Obtener el costo unitario del producto
            quantity_svl = self.product_id.sudo().quantity_svl
            value_svl = self.product_id.sudo().value_svl
            if quantity_svl > 0:
                unit_cost = value_svl / quantity_svl
                total_cost = unit_cost * self.product_qty
        
        for line in self.unbuild_line_ids:
            # Determinar ubicación destino
            if line.is_waste:
                # Buscar ubicación de desecho
                scrap_location = self.env['stock.location'].search([
                    ('scrap_location', '=', True),
                    ('company_id', 'in', [self.company_id.id, False])
                ], limit=1)
                
                if not scrap_location:
                    raise UserError(_('No se encontró ubicación de desecho configurada.'))
                
                dest_location = scrap_location
            else:
                dest_location = self.location_dest_id
            
            # Calcular precio unitario basado en cost_share (ya incluye value_factor)
            price_unit = 0.0
            if not line.is_waste and total_cost > 0 and line.actual_qty > 0:
                line_cost = total_cost * line.cost_share
                price_unit = line_cost / line.actual_qty
            
            # Crear movimiento
            move_vals = {
                'name': self.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.actual_qty,
                'product_uom': line.product_uom_id.id,
                'location_id': production_location.id,
                'location_dest_id': dest_location.id,
                'consume_unbuild_id': self.id,
                'company_id': self.company_id.id,
                'origin': self.name,
                'price_unit': price_unit,
            }
            
            moves |= self.env['stock.move'].create(move_vals)
        
        return moves
    
    def _prepare_move_lines(self, consume_move, produce_moves):
        """Prepara las líneas de movimiento con lotes si es necesario"""
        # Línea para el movimiento de consumo
        if self.lot_id:
            self.env['stock.move.line'].create({
                'move_id': consume_move.id,
                'lot_id': self.lot_id.id,
                'quantity': consume_move.product_uom_qty,
                'product_id': consume_move.product_id.id,
                'product_uom_id': consume_move.product_uom.id,
                'location_id': consume_move.location_id.id,
                'location_dest_id': consume_move.location_dest_id.id,
            })
        else:
            consume_move.quantity = consume_move.product_uom_qty
        
        # Líneas para movimientos de producción
        for move in produce_moves:
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
                message_body += _("- %(product)s: %(qty)s %(uom)s (%(cost).1f%% del costo)<br/>",
                    product=line.product_id.display_name,
                    qty=line.actual_qty,
                    uom=line.product_uom_id.name,
                    cost=line.cost_share * 100
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
            yield_pct=self.yield_percentage * 100
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