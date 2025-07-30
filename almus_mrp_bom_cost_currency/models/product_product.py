# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    manufacturing_alt_cost = fields.Monetary(
        string='Manufacturing Alt. Cost',
        compute='_compute_manufacturing_alt_cost',
        store=True,
        currency_field='alt_currency_id',
        help='Manufacturing cost calculated from BOM components alternative costs'
    )
    
    manufacturing_cost_state = fields.Selection([
        ('ok', 'OK'),
        ('warning', 'Warning'),
        ('no_bom', 'No BOM'),
        ('empty_bom', 'Empty BOM'),
    ], string='Manufacturing Cost State', 
       compute='_compute_manufacturing_alt_cost', 
       store=True,
       help='State of the manufacturing cost calculation')

    @api.depends('bom_ids', 'bom_ids.bom_line_ids', 'bom_ids.bom_line_ids.product_id.alt_cost')
    def _compute_manufacturing_alt_cost(self):
        """Compute manufacturing alternative cost based on BOM components"""
        # CORRECCIÓN: Crear caché de BOMs para evitar búsquedas repetitivas
        bom_cache = {}
        
        for product in self:
            cost, state = product._calculate_manufacturing_cost_recursive(bom_cache=bom_cache)
            product.manufacturing_alt_cost = cost
            product.manufacturing_cost_state = state

    def _calculate_manufacturing_cost_recursive(self, visited_products=None, bom_cache=None):
        """
        Calculate manufacturing cost recursively for products with BOM
        Returns: (cost, state)
        """
        self.ensure_one()
        
        if visited_products is None:
            visited_products = set()
        
        # CORRECCIÓN: Usar caché de BOMs para evitar búsquedas repetitivas
        if bom_cache is None:
            bom_cache = {}
        
        # Detectar dependencia circular
        if self.id in visited_products:
            _logger.warning(f"Circular dependency detected for product {self.display_name}")
            return 0.0, 'warning'
        
        # CORRECCIÓN: Obtener BOM del caché o buscarla una sola vez
        if self.id not in bom_cache:
            bom_cache[self.id] = self._get_main_bom()
        main_bom = bom_cache[self.id]
        
        if not main_bom:
            return 0.0, 'no_bom'
        
        if not main_bom.bom_line_ids:
            return 0.0, 'empty_bom'
        
        # Agregar producto actual al conjunto de visitados
        visited_products = visited_products.copy()
        visited_products.add(self.id)
        
        total_cost = 0.0
        has_warning = False
        
        for bom_line in main_bom.bom_line_ids:
            component = bom_line.product_id
            component_qty = bom_line.product_qty
            
            # CORRECCIÓN: Verificar y convertir monedas si son diferentes
            if component.alt_currency_id and self.alt_currency_id and component.alt_currency_id != self.alt_currency_id:
                # Convertir el costo del componente a la moneda del producto principal
                conversion_date = fields.Date.today()
            else:
                conversion_date = None
            
            # Si el componente tiene BoM, calcular recursivamente
            if component.id not in bom_cache:
                bom_cache[component.id] = component._get_main_bom()
            
            if bom_cache[component.id]:
                component_cost, component_state = component._calculate_manufacturing_cost_recursive(visited_products, bom_cache)
                if component_state != 'ok':
                    has_warning = True
            else:
                # Componente comprado, usar alt_cost
                if component.alt_cost and component.alt_cost > 0:
                    component_cost = component.alt_cost
                else:
                    component_cost = 0.0
                    has_warning = True
                    _logger.warning(f"Component {component.display_name} has no alternative cost")
            
            # CORRECCIÓN: Convertir moneda si es necesario antes de sumar
            if conversion_date and component.alt_currency_id and self.alt_currency_id:
                component_cost = component.alt_currency_id._convert(
                    component_cost,
                    self.alt_currency_id,
                    self.env.company,
                    conversion_date
                )
            
            # Sumar al costo total
            total_cost += component_cost * component_qty
        
        # Calcular costo unitario del producto final
        final_cost = total_cost / (main_bom.product_qty or 1.0)
        final_state = 'warning' if has_warning else 'ok'
        
        return final_cost, final_state

    def _get_main_bom(self):
        """Get the main active BOM for this product"""
        self.ensure_one()
        
        # CORRECCIÓN: Incluir filtro por empresa para soporte multi-empresa
        domain = [
            ('active', '=', True),
            '|',
                ('company_id', '=', False),
                ('company_id', '=', self.env.company.id),
        ]
        
        # Buscar BoM específica para este producto
        bom = self.env['mrp.bom'].search(
            domain + [('product_id', '=', self.id)],
            limit=1
        )
        
        if not bom:
            # Buscar BoM para el template
            bom = self.env['mrp.bom'].search(
                domain + [
                    ('product_tmpl_id', '=', self.product_tmpl_id.id),
                    ('product_id', '=', False),
                ],
                limit=1
            )
        
        return bom

    def has_bom(self):
        """Check if product has any active BOM"""
        self.ensure_one()
        return bool(self._get_main_bom())

    @api.model
    def _trigger_manufacturing_cost_recalc_for_dependents(self, changed_product_ids):
        """
        Trigger recalculation of manufacturing costs for products that depend on changed products
        """
        if not changed_product_ids:
            return
        
        # CORRECCIÓN: Usar conjunto para evitar recálculos duplicados
        # y BFS (Breadth-First Search) para recorrido eficiente
        to_recalculate = set()
        visited = set(changed_product_ids)
        queue = list(changed_product_ids)
        
        while queue:
            # Procesar en lotes para mejorar rendimiento
            current_id = queue.pop(0)
            
            # Buscar productos que tienen BoM que incluyen el producto actual
            dependent_bom_lines = self.env['mrp.bom.line'].search([
                ('product_id', '=', current_id)
            ])
            
            if not dependent_bom_lines:
                continue
            
            # Obtener productos que tienen estas BoMs
            for bom in dependent_bom_lines.mapped('bom_id'):
                if bom.product_id and bom.product_id.id not in visited:
                    to_recalculate.add(bom.product_id.id)
                    visited.add(bom.product_id.id)
                    queue.append(bom.product_id.id)
                elif not bom.product_id:
                    # BoM para template, buscar variantes
                    for variant in bom.product_tmpl_id.product_variant_ids:
                        if variant.id not in visited:
                            to_recalculate.add(variant.id)
                            visited.add(variant.id)
                            queue.append(variant.id)
        
        # CORRECCIÓN: Recalcular todos los productos afectados en una sola operación
        if to_recalculate:
            dependent_products = self.browse(list(to_recalculate))
            # Usar with_context para pasar información de que es una actualización en cascada
            dependent_products.with_context(cascade_update=True)._compute_manufacturing_alt_cost()

    def write(self, vals):
        """Override write to trigger recalculation when alt_cost changes"""
        result = super().write(vals)
        
        # Si se modificó alt_cost, recalcular productos dependientes
        if 'alt_cost' in vals:
            self._trigger_manufacturing_cost_recalc_for_dependents(self.ids)
        
        return result