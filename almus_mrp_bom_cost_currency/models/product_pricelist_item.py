# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_round
import logging

_logger = logging.getLogger(__name__)


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    # Extender el campo base para incluir la opción de costo alternativo de manufactura
    base = fields.Selection(
        selection_add=[
            ('manufacturing_alt_cost', 'Manufacturing Alternative Cost'),
        ],
        ondelete={'manufacturing_alt_cost': 'cascade'},
    )

    @api.constrains('base')
    def _check_manufacturing_alt_cost_configuration(self):
        """Validar que existe configuración adecuada cuando se usa manufacturing_alt_cost"""
        for item in self:
            if item.base == 'manufacturing_alt_cost':
                # Verificar configuración global de moneda alternativa
                alt_currency_id = self.env['ir.config_parameter'].sudo().get_param(
                    'almus_product_cost_currency.alt_currency_id'
                )
                if not alt_currency_id:
                    raise ValidationError(_(
                        'You must configure an alternative currency in settings before using '
                        'Manufacturing Alternative Cost as base for pricelist rules.'
                    ))

    def _compute_base_price(self, product, quantity, uom, date, currency):
        """Override to handle manufacturing alternative cost calculation"""
        
        # CORRECCIÓN: Verificar que self tenga registros antes de ensure_one()
        if not self:
            # Si no hay regla, usar el comportamiento estándar
            return super(ProductPricelistItem, self)._compute_base_price(
                product, quantity, uom, date, currency
            )
        
        self.ensure_one()
        
        # Si no es manufacturing_alt_cost, usar el comportamiento estándar
        if self.base != 'manufacturing_alt_cost':
            return super()._compute_base_price(product, quantity, uom, date, currency)
        
        # Validaciones iniciales
        currency.ensure_one()
        
        # Obtener el producto real (product.product) si es template
        if product._name == 'product.template':
            # Si el template tiene una sola variante, usar esa
            if len(product.product_variant_ids) == 1:
                product = product.product_variant_ids[0]
            else:
                # Si tiene múltiples variantes, no podemos determinar el costo
                raise ValidationError(_(
                    'Cannot use Manufacturing Alternative Cost for product templates with multiple variants. '
                    'Please create specific rules for each variant.'
                ))
        
        # Verificar que el producto tenga moneda alternativa configurada
        if not product.alt_currency_id:
            # Intentar obtener la moneda por defecto del parámetro de configuración
            param = self.env['ir.config_parameter'].sudo().get_param(
                'almus_product_cost_currency.alt_currency_id'
            )
            if param:
                try:
                    default_alt_currency_id = int(param)
                    # Asignar temporalmente para este cálculo (no guardar)
                    product = product.with_context(temp_alt_currency=default_alt_currency_id)
                    product.alt_currency_id = default_alt_currency_id
                except (ValueError, TypeError):
                    _logger.error(
                        "Invalid alternative currency parameter: %s",
                        param
                    )
                    raise ValidationError(_(
                        'Invalid alternative currency configuration. '
                        'Please check system settings.'
                    ))
            else:
                raise ValidationError(_(
                    'Product %s does not have an alternative currency configured, '
                    'and no default alternative currency is set in system settings.',
                    product.display_name
                ))
        
        # Determinar qué costo usar basado en si el producto es manufacturado
        try:
            if product.has_bom():
                # Producto manufacturado: usar manufacturing_alt_cost
                price = product.manufacturing_alt_cost
                
                # Solo advertir si el estado no es OK y el costo es 0
                if product.manufacturing_cost_state != 'ok' and price <= 0:
                    # Log discreto sin mostrar al usuario
                    _logger.debug(
                        'Product %s (ID: %s) has manufacturing cost issues. State: %s',
                        product.display_name,
                        product.id,
                        product.manufacturing_cost_state
                    )
            else:
                # Producto comprado: usar alt_cost como fallback
                price = product.alt_cost
                
                if price <= 0:
                    _logger.debug(
                        'Product %s (ID: %s) has no alternative cost defined',
                        product.display_name,
                        product.id
                    )
            
        except Exception as e:
            _logger.error(
                "Error determining cost for product %s: %s",
                product.display_name,
                str(e),
                exc_info=True
            )
            # Fallback seguro
            price = 0.0
        
        # Obtener moneda origen
        src_currency = product.alt_currency_id
        
        # Conversión de moneda si es necesario
        if src_currency and src_currency != currency:
            try:
                # Usar el método _convert con manejo de errores
                price = src_currency._convert(
                    price, 
                    currency, 
                    self.env.company, 
                    date, 
                    round=False  # No redondear aquí, se hará después
                )
            except Exception as e:
                _logger.error(
                    "Currency conversion failed from %s to %s for product %s: %s",
                    src_currency.name,
                    currency.name,
                    product.display_name,
                    str(e)
                )
                # En caso de error, intentar usar tasa directa
                try:
                    if src_currency.rate and currency.rate:
                        price = price * (currency.rate / src_currency.rate)
                    else:
                        price = 0.0
                except:
                    price = 0.0
        
        # Manejar conversión de UoM si es necesario
        if uom and product.uom_id != uom:
            try:
                price = product.uom_id._compute_price(price, uom)
            except Exception as e:
                _logger.error(
                    "UoM conversion failed for product %s: %s",
                    product.display_name,
                    str(e)
                )
        
        # Aplicar redondeo final según la precisión de la moneda destino
        if currency and hasattr(currency, 'rounding'):
            price = float_round(price, precision_rounding=currency.rounding)
        
        return price

    @api.onchange('base')
    def _onchange_base_manufacturing_alt_cost(self):
        """Mostrar advertencia cuando se selecciona manufacturing_alt_cost"""
        if self.base == 'manufacturing_alt_cost':
            # Verificar si hay moneda alternativa configurada
            alt_currency_id = self.env['ir.config_parameter'].sudo().get_param(
                'almus_product_cost_currency.alt_currency_id'
            )
            if not alt_currency_id:
                return {
                    'warning': {
                        'title': _('Configuration Required'),
                        'message': _(
                            'No alternative currency configured. Please configure it in '
                            'Settings > Almus Apps > Cost Settings before using this option.\n\n'
                            'This option calculates prices based on manufacturing costs '
                            'in the alternative currency.'
                        )
                    }
                }

    def _is_applicable_for(self, product, qty_in_product_uom):
        """Override to ensure manufacturing_alt_cost rules work correctly"""
        res = super()._is_applicable_for(product, qty_in_product_uom)
        
        if not res:
            return False
        
        # Si la regla usa manufacturing_alt_cost, hacer validaciones adicionales
        if self.base == 'manufacturing_alt_cost':
            # Para templates con múltiples variantes
            if product._name == 'product.template' and len(product.product_variant_ids) > 1:
                # Esta regla no es aplicable para templates con múltiples variantes
                return False
            
            # Verificar que el producto tenga configuración válida
            # (pero no lanzar excepción aquí, solo retornar False)
            if product._name == 'product.product':
                if not product.alt_currency_id:
                    # Verificar si hay moneda por defecto
                    param = self.env['ir.config_parameter'].sudo().get_param(
                        'almus_product_cost_currency.alt_currency_id'
                    )
                    if not param:
                        return False
        
        return res

    @api.model
    def _get_pricelist_items_for_product(self, product, quantity, uom, date, currency):
        """
        Método helper para obtener items de lista de precios aplicables
        con caché mejorado (si se implementa en el futuro)
        """
        # Este método puede ser extendido en el futuro para implementar
        # caché de reglas de lista de precios si es necesario
        items = self.search([
            ('product_id', '=', product.id),
            '|', ('date_start', '=', False), ('date_start', '<=', date),
            '|', ('date_end', '=', False), ('date_end', '>=', date),
        ])
        
        # Filtrar por cantidad mínima
        items = items.filtered(
            lambda r: r.min_quantity <= quantity
        )
        
        return items.sorted('min_quantity', reverse=True)