# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _get_default_alt_currency(self):
        """Get the default alternative currency from settings"""
        param = self.env['ir.config_parameter'].sudo().get_param('almus_product_cost_currency.alt_currency_id')
        if param:
            try:
                return int(param)
            except (ValueError, TypeError):
                _logger.warning("Invalid alternative currency parameter: %s", param)
                return False
        # If no parameter set, try to return USD as default
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        return usd.id if usd else False

    alt_currency_id = fields.Many2one(
        'res.currency',
        string='Alternative Currency',
        default=_get_default_alt_currency,
        help='Alternative currency used to display cost'
    )
    
    alt_cost = fields.Monetary(
        string='Cost in Alt. Currency',
        compute='_compute_alt_cost',
        store=True,
        currency_field='alt_currency_id',
        help='Product cost converted to the alternative currency',
        readonly=True
    )

    @api.depends('standard_price', 'alt_currency_id', 'company_id')
    def _compute_alt_cost(self):
        """Compute cost in the alternative currency"""
        for product in self:
            if product.alt_currency_id and product.standard_price:
                try:
                    # Get the source currency (standard_price is in company currency)
                    if product.company_id:
                        from_currency = product.company_id.currency_id
                    else:
                        from_currency = self.env.company.currency_id
                    
                    to_currency = product.alt_currency_id
                    
                    if from_currency != to_currency:
                        # Check if rate exists
                        if not to_currency.rate:
                            _logger.warning(
                                "No exchange rate found for currency %s (ID: %s) for product %s", 
                                to_currency.name, to_currency.id, product.display_name
                            )
                            product.alt_cost = 0.0
                            continue
                            
                        product.alt_cost = from_currency._convert(
                            product.standard_price,
                            to_currency,
                            product.company_id or self.env.company,
                            fields.Date.today()
                        )
                    else:
                        product.alt_cost = product.standard_price
                        
                except Exception as e:
                    _logger.error(
                        "Error converting cost for product %s: %s", 
                        product.display_name, str(e)
                    )
                    product.alt_cost = 0.0
            else:
                product.alt_cost = 0.0

    @api.model
    def create(self, vals):
        """Override create to set default alt_currency_id if not provided"""
        if 'alt_currency_id' not in vals:
            vals['alt_currency_id'] = self._get_default_alt_currency()
        return super().create(vals)

    @api.model
    def _update_alt_currency_from_settings(self, currency_id):
        """Update alternative currency for all products when settings change"""
        total_products = self.search_count([])
        if total_products == 0:
            return True
            
        batch_size = 500
        offset = 0
        updated = 0
        
        _logger.info("Starting alternative currency update for %s products", total_products)
        
        # Use SQL for better performance on very large datasets
        if total_products > 5000:
            _logger.info("Using SQL update for better performance")
            self._cr.execute("""
                UPDATE product_product 
                SET alt_currency_id = %s
                WHERE active = true
            """, (currency_id,))
            updated = self._cr.rowcount
            # Invalidate cache to ensure computed fields are recalculated
            self.invalidate_cache(['alt_currency_id'])
            _logger.info("Updated %s products via SQL", updated)
        else:
            # Use ORM for smaller datasets to trigger all business logic
            while offset < total_products:
                products = self.search([], offset=offset, limit=batch_size)
                if not products:
                    break
                    
                try:
                    products.write({'alt_currency_id': currency_id})
                    updated += len(products)
                    self.env.cr.commit()  # Commit after each batch
                    
                    _logger.info("Updated batch %s-%s of %s products", 
                               offset + 1, 
                               min(offset + batch_size, total_products), 
                               total_products)
                except Exception as e:
                    _logger.error("Error updating batch at offset %s: %s", offset, str(e))
                    self.env.cr.rollback()
                    
                offset += batch_size
                
        _logger.info("Finished updating alternative currency. Total updated: %s", updated)
        return True

    @api.model
    def action_recalculate_alt_costs(self):
        """Force recalculation of alternative costs for all products"""
        products = self.search([('alt_currency_id', '!=', False)])
        total = len(products)
        
        if total == 0:
            _logger.info("No products with alternative currency to recalculate")
            return True
            
        _logger.info("Recalculating alternative costs for %s products", total)
        
        # Force recomputation by clearing and triggering dependency
        products._compute_alt_cost()
        
        _logger.info("Finished recalculating alternative costs")
        return True