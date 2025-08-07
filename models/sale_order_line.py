# Copyright 2019 Tecnativa - Ernesto Tejeda
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import first


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"
    _parent_name = "pack_parent_line_id"

    pack_type = fields.Selection(
        related="product_id.pack_type",
    )
    pack_component_price = fields.Selection(
        related="product_id.pack_component_price",
    )

    # Campos para paquetes comunes
    pack_depth = fields.Integer(
        "Profundidad", help="Profundidad del producto si es parte de un paquete."
    )
    pack_parent_line_id = fields.Many2one(
        "sale.order.line",
        "Paquete",
        help="El paquete que contiene este producto.",
    )
    pack_child_line_ids = fields.One2many(
        "sale.order.line", "pack_parent_line_id", "Líneas en paquete"
    )
    pack_modifiable = fields.Boolean(help="El paquete padre es modificable")

    do_no_expand_pack_lines = fields.Boolean(
        compute="_compute_do_no_expand_pack_lines",
        help="Este es un campo técnico para verificar si las líneas del paquete deben expandirse",
    )

    @api.depends_context("update_prices", "update_pricelist")
    def _compute_do_no_expand_pack_lines(self):
        do_not_expand = self.env.context.get("update_prices") or self.env.context.get(
            "update_pricelist", False
        )
        self.update(
            {
                "do_no_expand_pack_lines": do_not_expand,
            }
        )

    def expand_pack_line(self, write=False):
        self.ensure_one()
        # si estamos usando update_pricelist o comprando en ecommerce solo
        # queremos actualizar precios
        vals_list = []
        if self.product_id.pack_ok and self.pack_type == "detailed":
            for subline in self.product_id.get_pack_lines():
                vals = subline.get_sale_order_line_vals(self, self.order_id)
                
                # 🆕 APLICAR LÓGICA DE desglosar_iva DESPUÉS DE OBTENER LOS VALORES
                if hasattr(self.order_id, 'desglosar_iva') and not self.order_id.desglosar_iva:
                    # Si desglosar_iva está desactivado y el precio no incluye IVA, aplicarlo
                    if vals.get("price_unit", 0) > 0:
                        # Verificar si ya tiene IVA aplicado (evitar duplicación)
                        original_price = vals["price_unit"]
                        # Aplicar IVA si no está ya incluido
                        vals["price_unit"] = original_price * 1.16
                
                if write:
                    existing_subline = first(
                        self.pack_child_line_ids.filtered(
                            lambda child: child.product_id == subline.product_id
                        )
                    )
                    # si la sublínea ya existe la actualizamos, si no la creamos
                    if existing_subline:
                        if self.do_no_expand_pack_lines:
                            vals.pop("product_uom_qty", None)
                            vals.pop("discount", None)
                        existing_subline.write(vals)
                    elif not self.do_no_expand_pack_lines:
                        vals_list.append(vals)
                else:
                    vals_list.append(vals)
            if vals_list:
                self.create(vals_list)

    @api.model_create_multi
    def create(self, vals_list):
        """Solo cuando sea estrictamente necesario (un producto es un paquete) se creará línea
        por línea, esto es necesario para mantener el orden correcto.
        """
        product_ids = [elem.get("product_id") for elem in vals_list]
        products = self.env["product.product"].browse(product_ids)
        if any(p.pack_ok and p.pack_type != "non_detailed" for p in products):
            res = self.browse()
            for elem in vals_list:
                line = super().create([elem])
                product = line.product_id
                res += line
                if product and product.pack_ok and product.pack_type != "non_detailed":
                    line.expand_pack_line()
                    
                    # 🆕 APLICAR LÓGICA DE desglosar_iva DESPUÉS DE EXPANDIR PAQUETE
                    if hasattr(line.order_id, 'desglosar_iva') and not line.order_id.desglosar_iva:
                        # Actualizar precios de las líneas hijo para incluir IVA
                        for child_line in line.pack_child_line_ids:
                            if child_line.price_unit > 0:
                                # Verificar si el precio ya incluye IVA comparando con el precio base
                                base_price = child_line.product_id.list_price or 0
                                if base_price > 0 and abs(child_line.price_unit - base_price) < 0.01:
                                    # El precio parece ser el precio base, aplicar IVA
                                    child_line.price_unit = child_line.price_unit * 1.16
            return res
        else:
            return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if "product_id" in vals or "product_uom_qty" in vals:
            for record in self:
                record.expand_pack_line(write=True)
        return res

    @api.onchange(
        "product_id",
        "product_uom_qty",
        "product_uom",
        "price_unit",
        "discount",
        "name",
        "tax_id",
    )
    def check_pack_line_modify(self):
        """No permitir editar una línea de orden de venta si pertenece a un paquete"""
        if self._origin.pack_parent_line_id and not self._origin.pack_modifiable:
            raise UserError(
                _(
                    "No puedes cambiar esta línea porque es parte de un paquete "
                    "incluido en esta orden"
                )
            )

    def action_open_parent_pack_product_view(self):
        domain = [
            ("id", "in", self.mapped("pack_parent_line_id").mapped("product_id").ids)
        ]
        return {
            "name": _("Producto Padre"),
            "type": "ir.actions.act_window",
            "res_model": "product.product",
            "view_type": "form",
            "view_mode": "tree,form",
            "domain": domain,
        }