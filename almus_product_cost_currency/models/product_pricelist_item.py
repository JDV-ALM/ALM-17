# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    # Extender el campo base para incluir la opción de costo alternativo
    base = fields.Selection(
        selection_add=[
            ('alt_cost', 'Alternative Cost'),
        ],
        ondelete={'alt_cost': 'cascade'},
    )

    @api.constrains('base')
    def _check_alt_cost_configuration(self):
        """Validar que existe una moneda alternativa configurada cuando se usa alt_cost"""
        for item in self:
            if item.base == 'alt_cost':
                # Verificar configuración global
                alt_currency_id = self.env['ir.config_parameter'].sudo().get_param(
                    'almus_product_cost_currency.alt_currency_id'
                )
                if not alt_currency_id:
                    raise ValidationError(_(
                        'You must configure an alternative currency in settings before using '
                        'Alternative Cost as base for pricelist rules.'
                    ))

    def _compute_base_price(self, product, quantity, uom, date, currency):
        """Override to handle alternative cost calculation"""
        self.ensure_one()
        
        # Si no es alt_cost, usar el comportamiento estándar
        if self.base != 'alt_cost':
            return super()._compute_base_price(product, quantity, uom, date, currency)
        
        # Lógica para alt_cost
        currency.ensure_one()
        
        # Obtener el producto real (product.product) si es template
        if product._name == 'product.template':
            # Si el template tiene una sola variante, usar esa
            if len(product.product_variant_ids) == 1:
                product = product.product_variant_ids[0]
            else:
                # Si tiene múltiples variantes, no podemos determinar el costo alternativo
                raise ValidationError(_(
                    'Cannot use Alternative Cost for product templates with multiple variants. '
                    'Please create specific rules for each variant.'
                ))
        
        # Verificar que el producto tenga moneda alternativa configurada
        if not product.alt_currency_id:
            # Intentar obtener la moneda por defecto del parámetro de configuración
            param = self.env['ir.config_parameter'].sudo().get_param(
                'almus_product_cost_currency.alt_currency_id'
            )
            if param:
                default_alt_currency_id = int(param)
                product.alt_currency_id = default_alt_currency_id
            else:
                raise ValidationError(_(
                    'Product %s does not have an alternative currency configured.',
                    product.display_name
                ))
        
        # Asegurarse de que el costo alternativo esté calculado
        if product.alt_cost == 0.0 and product.standard_price > 0:
            # Forzar el cálculo si no está computado
            product._compute_alt_cost()
        
        price = product.alt_cost
        src_currency = product.alt_currency_id
        
        # Si la moneda origen es diferente a la moneda destino, convertir
        if src_currency != currency:
            price = src_currency._convert(
                price, 
                currency, 
                self.env.company, 
                date, 
                round=False
            )
        
        # Manejar conversión de UoM si es necesario
        if uom and product.uom_id != uom:
            price = product.uom_id._compute_price(price, uom)
        
        return price

    @api.onchange('base')
    def _onchange_base_alt_cost(self):
        """Mostrar advertencia cuando se selecciona alt_cost"""
        if self.base == 'alt_cost':
            # Verificar si hay moneda alternativa configurada
            alt_currency_id = self.env['ir.config_parameter'].sudo().get_param(
                'almus_product_cost_currency.alt_currency_id'
            )
            if not alt_currency_id:
                return {
                    'warning': {
                        'title': _('Warning'),
                        'message': _(
                            'No alternative currency configured. Please configure it in '
                            'Settings > Almus Apps > Cost Settings before using this option.'
                        )
                    }
                }

    def _is_applicable_for(self, product, qty_in_product_uom):
        """Override to ensure alt_cost rules work correctly with templates"""
        res = super()._is_applicable_for(product, qty_in_product_uom)
        
        # Si la regla usa alt_cost y el producto es un template con múltiples variantes
        if res and self.base == 'alt_cost' and product._name == 'product.template':
            if len(product.product_variant_ids) > 1:
                # Esta regla no es aplicable para templates con múltiples variantes
                return False
        
        return res