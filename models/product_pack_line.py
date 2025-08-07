# Copyright 2019 Tecnativa - Ernesto Tejeda
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class ProductPack(models.Model):
    _inherit = "product.pack.line"

    sale_discount = fields.Float(
        "Descuento de venta (%)",
        digits="Discount",
    )

    def get_sale_order_line_vals(self, line, order):
        self.ensure_one()
        quantity = self.quantity * line.product_uom_qty
        line_vals = {
            "order_id": order.id,
            "sequence": line.sequence,
            "product_id": self.product_id.id or False,
            "pack_parent_line_id": line.id,
            "pack_depth": line.pack_depth + 1,
            "company_id": order.company_id.id,
            "pack_modifiable": line.product_id.pack_modifiable,
            "product_uom_qty": quantity,
        }
        sol = line.new(line_vals)
        sol._onchange_product_id_warning()
        vals = sol._convert_to_write(sol._cache)
        pack_price_types = {"totalized", "ignored"}
        sale_discount = 0.0
        
        # Verificar si desglosar_iva está desactivado en la orden padre
        desglosar_iva = getattr(order, 'desglosar_iva', True)  # Por defecto True si no existe el campo
        
        if line.product_id.pack_component_price == "detailed":
            sale_discount = 100.0 - (
                (100.0 - sol.discount) * (100.0 - self.sale_discount) / 100.0
            )
            
            # 🔧 AJUSTE: Aplicar IVA directamente al precio si desglosar_iva está desactivado
            if not desglosar_iva and vals.get("price_unit", 0) > 0:
                # Si desglosar_iva está desactivado, multiplicar precio por 1.16 (incluir IVA)
                vals["price_unit"] = vals["price_unit"] * 1.16
                
        elif (
            line.product_id.pack_type == "detailed"
            and line.product_id.pack_component_price in pack_price_types
        ):
            vals["price_unit"] = 0.0
            
        # 🆕 NUEVO: Aplicar IVA también para paquetes no detallados si desglosar_iva está desactivado
        elif not desglosar_iva and vals.get("price_unit", 0) > 0:
            vals["price_unit"] = vals["price_unit"] * 1.16
        
        vals.update(
            {
                "discount": sale_discount,
                "name": "{}{}".format("> " * (line.pack_depth + 1), sol.name),
            }
        )
        return vals

    def get_price(self):
        self.ensure_one()
        # Obtener el precio base con descuento aplicado
        base_price = super().get_price() * (1 - self.sale_discount / 100.0)
        return base_price