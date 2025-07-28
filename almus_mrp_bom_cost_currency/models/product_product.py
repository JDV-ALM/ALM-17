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
        for product in self:
            cost, state = product._calculate_manufacturing_cost_recursive()
            product.manufacturing_alt_cost = cost
            product.manufacturing_cost_state = state

    def _calculate_manufacturing_cost_recursive(self, visited_products=None):
        """
        Calculate manufacturing cost recursively for products with BOM
        Returns: (cost, state)
        """
        self.ensure_one()
        
        if visited_products is None:
            visited_products = set()
        
        # Detectar dependencia circular
        if self.id in visited_products:
            _logger.warning(f"Circular dependency detected for product {self.display_name}")
            return 0.0, 'warning'
        
        # Obtener BoM principal
        main_bom = self._get_main_bom()
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
            
            # Si el componente tiene BoM, calcular recursivamente
            component_bom = component._get_main_bom()
            if component_bom:
                component_cost, component_state = component._calculate_manufacturing_cost_recursive(visited_products)
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
            
            # Sumar al costo total
            total_cost += component_cost * component_qty
        
        # Calcular costo unitario del producto final
        final_cost = total_cost / (main_bom.product_qty or 1.0)
        final_state = 'warning' if has_warning else 'ok'
        
        return final_cost, final_state

    def _get_main_bom(self):
        """Get the main active BOM for this product"""
        self.ensure_one()
        
        # Buscar BoM específica para este producto
        bom = self.env['mrp.bom'].search([
            ('product_id', '=', self.id),
            ('active', '=', True),
        ], limit=1)
        
        if not bom:
            # Buscar BoM para el template
            bom = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', self.product_tmpl_id.id),
                ('product_id', '=', False),
                ('active', '=', True),
            ], limit=1)
        
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
        
        # Buscar productos que tienen BoM que incluyen los productos modificados
        dependent_bom_lines = self.env['mrp.bom.line'].search([
            ('product_id', 'in', changed_product_ids)
        ])
        
        if not dependent_bom_lines:
            return
        
        # Obtener productos que tienen estas BoMs
        dependent_boms = dependent_bom_lines.mapped('bom_id')
        dependent_product_ids = []
        
        for bom in dependent_boms:
            if bom.product_id:
                dependent_product_ids.append(bom.product_id.id)
            else:
                # BoM para template, buscar variantes
                variant_ids = bom.product_tmpl_id.product_variant_ids.ids
                dependent_product_ids.extend(variant_ids)
        
        if dependent_product_ids:
            dependent_products = self.browse(dependent_product_ids)
            dependent_products._compute_manufacturing_alt_cost()
            
            # Recursivamente actualizar dependientes de dependientes
            self._trigger_manufacturing_cost_recalc_for_dependents(dependent_product_ids)

    def write(self, vals):
        """Override write to trigger recalculation when alt_cost changes"""
        result = super().write(vals)
        
        # Si se modificó alt_cost, recalcular productos dependientes
        if 'alt_cost' in vals:
            self._trigger_manufacturing_cost_recalc_for_dependents(self.ids)
        
        return result