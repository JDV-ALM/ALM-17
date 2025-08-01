# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_round
from functools import lru_cache
from collections import defaultdict
import logging

_logger = logging.getLogger(__name__)

# Constantes de configuración
MAX_BOM_RECURSION_DEPTH = 20  # Límite máximo de anidamiento de BOMs
BATCH_SIZE = 100  # Tamaño de lote para procesamiento masivo
CURRENCY_CACHE_SIZE = 128  # Tamaño del caché de conversión de moneda


class ProductProduct(models.Model):
    _inherit = 'product.product'

    manufacturing_alt_cost = fields.Monetary(
        string='Manufacturing Alt. Cost',
        compute='_compute_manufacturing_alt_cost',
        store=True,
        currency_field='alt_currency_id',
        digits='Product Price',  # Usar precisión configurada
        help='Manufacturing cost calculated from BOM components alternative costs'
    )
    
    manufacturing_cost_state = fields.Selection([
        ('ok', 'OK'),
        ('warning', 'Warning'),
        ('no_bom', 'No BOM'),
        ('empty_bom', 'Empty BOM'),
        ('error', 'Error'),  # Nuevo estado para errores
    ], string='Manufacturing Cost State', 
       compute='_compute_manufacturing_alt_cost', 
       store=True,
       help='State of the manufacturing cost calculation')

    @api.model
    @lru_cache(maxsize=CURRENCY_CACHE_SIZE)
    def _get_currency_rate_cached(self, from_currency_id, to_currency_id, company_id, date_str):
        """
        Caché de tasas de cambio para evitar consultas repetitivas
        Nota: Usamos date_str porque date objects no son hashables
        """
        from_currency = self.env['res.currency'].browse(from_currency_id)
        to_currency = self.env['res.currency'].browse(to_currency_id)
        company = self.env['res.company'].browse(company_id)
        date = fields.Date.from_string(date_str)
        
        # Si las monedas son iguales, no hay conversión
        if from_currency_id == to_currency_id:
            return 1.0
        
        # Calcular tasa usando el método interno de Odoo
        return from_currency._get_conversion_rate(
            from_currency, 
            to_currency, 
            company, 
            date
        )

    @api.depends('bom_ids', 'bom_ids.bom_line_ids', 'bom_ids.bom_line_ids.product_id.alt_cost',
                 'bom_ids.bom_line_ids.product_id.manufacturing_alt_cost')
    def _compute_manufacturing_alt_cost(self):
        """Compute manufacturing alternative cost with batch processing"""
        
        # Dividir en lotes para mejor rendimiento
        all_products = self
        total = len(all_products)
        
        # Pre-cargar BOMs para todos los productos
        all_product_ids = all_products.ids
        boms_data = self.env['mrp.bom'].search_read(
            [
                ('active', '=', True),
                '|',
                    ('product_id', 'in', all_product_ids),
                    '&',
                        ('product_tmpl_id', 'in', all_products.mapped('product_tmpl_id').ids),
                        ('product_id', '=', False),
                '|',
                    ('company_id', '=', False),
                    ('company_id', '=', self.env.company.id),
            ],
            ['product_id', 'product_tmpl_id', 'product_qty']
        )
        
        # Crear mapeo rápido de producto -> BOM
        product_bom_map = {}
        template_bom_map = defaultdict(list)
        
        for bom in boms_data:
            if bom['product_id']:
                product_bom_map[bom['product_id'][0]] = bom['id']
            else:
                template_bom_map[bom['product_tmpl_id'][0]].append(bom['id'])
        
        # Procesar en lotes
        for i in range(0, total, BATCH_SIZE):
            batch = all_products[i:i + BATCH_SIZE]
            
            # Limpiar caché para cada lote
            self._get_currency_rate_cached.cache_clear()
            
            # Crear caché de BOMs para el lote
            bom_cache = {}
            
            for product in batch:
                try:
                    # Buscar BOM en mapeo pre-cargado
                    if product.id in product_bom_map:
                        bom_cache[product.id] = self.env['mrp.bom'].browse(product_bom_map[product.id])
                    elif product.product_tmpl_id.id in template_bom_map:
                        # Tomar el primer BOM del template
                        bom_ids = template_bom_map[product.product_tmpl_id.id]
                        if bom_ids:
                            bom_cache[product.id] = self.env['mrp.bom'].browse(bom_ids[0])
                    
                    cost, state = product._calculate_manufacturing_cost_recursive(
                        bom_cache=bom_cache,
                        depth=0
                    )
                    
                    product.manufacturing_alt_cost = cost
                    product.manufacturing_cost_state = state
                    
                except Exception as e:
                    _logger.error(
                        "Failed to calculate manufacturing cost for product %s (ID: %s): %s",
                        product.display_name, product.id, str(e),
                        exc_info=True
                    )
                    product.manufacturing_alt_cost = 0.0
                    product.manufacturing_cost_state = 'error'

    def _calculate_manufacturing_cost_recursive(self, visited_products=None, bom_cache=None, depth=0):
        """
        Calculate manufacturing cost recursively with optimizations
        Returns: (cost, state)
        """
        self.ensure_one()
        
        # Verificar límite de profundidad
        if depth > MAX_BOM_RECURSION_DEPTH:
            _logger.error(
                "Maximum BOM recursion depth (%s) exceeded for product %s (ID: %s)",
                MAX_BOM_RECURSION_DEPTH, self.display_name, self.id
            )
            return 0.0, 'warning'
        
        if visited_products is None:
            visited_products = set()
        
        if bom_cache is None:
            bom_cache = {}
        
        # Detectar dependencia circular
        if self.id in visited_products:
            if depth <= 5:  # Solo loguear en niveles superiores
                _logger.warning(
                    "Circular dependency detected for product %s at depth %s",
                    self.display_name, depth
                )
            return 0.0, 'warning'
        
        # Obtener BOM del caché
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
        
        # Preparar datos para conversión de moneda
        conversion_date = fields.Date.context_today(self)
        conversion_date_str = fields.Date.to_string(conversion_date)
        target_currency = self.alt_currency_id
        company = self.env.company
        
        # Pre-cargar líneas de BOM con sus productos
        bom_lines_data = main_bom.bom_line_ids.read(['product_id', 'product_qty'])
        component_ids = [line['product_id'][0] for line in bom_lines_data]
        components = self.browse(component_ids)
        
        # Pre-cargar BOMs de componentes
        for component in components:
            if component.id not in bom_cache:
                bom_cache[component.id] = component._get_main_bom()
        
        total_cost = 0.0
        has_warning = False
        currency_rounding = target_currency.rounding if target_currency else 0.01
        
        # Procesar cada línea de BOM
        for line_data, component in zip(bom_lines_data, components):
            component_qty = line_data['product_qty']
            
            try:
                # Determinar si el componente tiene BOM
                has_bom = bool(bom_cache.get(component.id))
                
                # Calcular costo del componente
                if has_bom:
                    # Recursión con incremento de profundidad
                    component_cost, component_state = component._calculate_manufacturing_cost_recursive(
                        visited_products, 
                        bom_cache,
                        depth + 1
                    )
                    if component_state != 'ok':
                        has_warning = True
                else:
                    # Componente comprado
                    component_cost = component.alt_cost
                    if not component_cost or component_cost <= 0:
                        has_warning = True
                        component_cost = 0.0
                
                # Convertir moneda si es necesario
                if (component_cost > 0 and 
                    component.alt_currency_id and 
                    target_currency and 
                    component.alt_currency_id.id != target_currency.id):
                    
                    # Usar caché para conversión
                    rate = self._get_currency_rate_cached(
                        component.alt_currency_id.id,
                        target_currency.id,
                        company.id,
                        conversion_date_str
                    )
                    component_cost = component_cost * rate
                
                # Calcular costo de línea con precisión correcta
                line_cost = float_round(
                    component_cost * component_qty,
                    precision_rounding=currency_rounding
                )
                total_cost += line_cost
                
            except Exception as e:
                _logger.error(
                    "Error calculating cost for component %s in BOM of %s: %s",
                    component.display_name, self.display_name, str(e)
                )
                has_warning = True
                continue
        
        # Calcular costo unitario del producto final
        try:
            final_cost = float_round(
                total_cost / (main_bom.product_qty or 1.0),
                precision_rounding=currency_rounding
            )
        except (ZeroDivisionError, TypeError) as e:
            _logger.error(
                "Error calculating final cost for %s: %s",
                self.display_name, str(e)
            )
            final_cost = 0.0
            has_warning = True
        
        final_state = 'warning' if has_warning else 'ok'
        
        return final_cost, final_state

    def _get_main_bom(self):
        """Get the main active BOM for this product (optimized version)"""
        self.ensure_one()
        
        # Dominio base con filtro de empresa
        domain = [
            ('active', '=', True),
            '|',
                ('company_id', '=', False),
                ('company_id', '=', self.env.company.id),
        ]
        
        # Buscar BoM específica para este producto primero
        bom = self.env['mrp.bom'].search(
            domain + [('product_id', '=', self.id)],
            limit=1,
            order='sequence, id'  # Respetar secuencia si hay múltiples
        )
        
        if not bom:
            # Buscar BoM para el template
            bom = self.env['mrp.bom'].search(
                domain + [
                    ('product_tmpl_id', '=', self.product_tmpl_id.id),
                    ('product_id', '=', False),
                ],
                limit=1,
                order='sequence, id'
            )
        
        return bom

    def has_bom(self):
        """Check if product has any active BOM (cached during batch processing)"""
        self.ensure_one()
        # Este método será más eficiente cuando se use dentro del contexto
        # de _compute_manufacturing_alt_cost debido al pre-cargado
        return bool(self._get_main_bom())

    @api.model
    def _trigger_manufacturing_cost_recalc_for_dependents(self, changed_product_ids):
        """
        Trigger recalculation using batch processing for better performance
        """
        if not changed_product_ids:
            return
        
        try:
            # Usar read_group para obtener todos los productos dependientes eficientemente
            bom_line_data = self.env['mrp.bom.line'].read_group(
                [('product_id', 'in', list(changed_product_ids))],
                ['bom_id:array_agg'],
                [],
                lazy=False
            )
            
            if not bom_line_data:
                return
            
            # Extraer todos los BOM IDs
            all_bom_ids = []
            if bom_line_data and bom_line_data[0].get('bom_id'):
                all_bom_ids = bom_line_data[0]['bom_id']
            
            if not all_bom_ids:
                return
            
            # Obtener productos afectados de los BOMs
            affected_products = self.env['mrp.bom'].browse(all_bom_ids).mapped(
                lambda b: b.product_id or b.product_tmpl_id.product_variant_ids
            )
            
            # Filtrar productos que no estaban en la lista original
            products_to_update = affected_products.filtered(
                lambda p: p.id not in changed_product_ids
            )
            
            if products_to_update:
                # Actualizar con contexto especial para evitar recursión infinita
                products_to_update.with_context(
                    cascade_update=True,
                    no_commit=True  # Evitar commits intermedios
                )._compute_manufacturing_alt_cost()
                
        except Exception as e:
            _logger.error(
                "Failed to trigger dependent recalculation for products %s: %s",
                changed_product_ids, str(e),
                exc_info=True
            )

    def write(self, vals):
        """Override write to trigger recalculation when alt_cost changes"""
        # Guardar IDs antes de la escritura
        if 'alt_cost' in vals and not self.env.context.get('cascade_update'):
            products_changed = self.ids
        else:
            products_changed = []
        
        # Realizar escritura
        result = super().write(vals)
        
        # Disparar recálculo si es necesario
        if products_changed:
            try:
                self._trigger_manufacturing_cost_recalc_for_dependents(products_changed)
            except Exception as e:
                # No fallar la operación principal
                _logger.error(
                    "Failed to update dependent products after alt_cost change: %s",
                    str(e)
                )
        
        return result

    @api.model
    def clear_currency_cache(self):
        """Limpiar caché de conversión de moneda (útil para tareas programadas)"""
        self._get_currency_rate_cached.cache_clear()
        _logger.info("Currency conversion cache cleared")