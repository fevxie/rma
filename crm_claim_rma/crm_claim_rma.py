# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright 2013 Camptocamp
#    Copyright 2009-2013 Akretion,
#    Author: Emmanuel Samyn, Raphaël Valyi, Sébastien Beau,
#            Benoît Guillot, Joel Grand-Guillaume
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
import calendar
import math
from openerp import fields, models, api, exceptions
from openerp.osv import osv, orm
from datetime import datetime
from dateutil.relativedelta import relativedelta
from openerp.tools import (DEFAULT_SERVER_DATE_FORMAT,
                           DEFAULT_SERVER_DATETIME_FORMAT)
from openerp.tools.translate import _


class InvoiceNoDate(Exception):
    """ Raised when a warranty cannot be computed for a claim line
    because the invoice has no date. """


class ProductNoSupplier(Exception):
    """ Raised when a warranty cannot be computed for a claim line
    because the product has no supplier. """


class Substate(models.Model):
    """ To precise a state (state=refused; substates= reason 1, 2,...) """
    _name = "substate.substate"
    _description = "substate that precise a given state"
    name = fields.Char(
        string='Sub state', required=True)
    substate_descr = fields.Text(
        string='Description',
        help="To give more information about the sub state")


class ClaimLine(models.Model):
    """
    Class to handle a product return line (corresponding to one invoice line)
    """
    _name = "claim.line"
    _description = "List of product to return"

    # Comment written in a claim.line to know about the warranty status
    WARRANT_COMMENT = {
        'valid': "Valid",
        'expired': "Expired",
        'not_define': "Not Defined"}

    # Method to calculate total amount of the line : qty*UP
    @api.one
    @api.depends('unit_sale_price', 'product_returned_quantity')
    def _line_total_amount(self):
        for line in self:
            self.return_value = (line.unit_sale_price *
                                 line.product_returned_quantity)

    @api.multi
    def copy_data(self, default=None):
        if default is None:
            default = {}
        self.ensure_one()
        std_default = {
            'move_in_id': False,
            'move_out_id': False,
            'refund_line_id': False,
        }
        std_default.update(default)
        return super(ClaimLine, self).copy_data(default=std_default)

    @api.model
    def get_warranty_return_partner(self):
        seller = self.env['product.supplierinfo']
        result = seller.get_warranty_return_partner()
        return result

    name = fields.Char(
        string='Description',
        required=True,
        default='none')
    claim_origine = fields.Selection(
        selection=[
            ('none', 'Not specified'),
            ('legal', 'Legal retractation'),
            ('cancellation', 'Order cancellation'),
            ('damaged', 'Damaged delivered product'),
            ('error', 'Shipping error'),
            ('exchange', 'Exchange request'),
            ('lost', 'Lost during transport'),
            ('other', 'Other')
        ],
        string='Claim Subject',
        required=True,
        help="To describe the line product problem")
    claim_descr = fields.Text(
        string='Claim description',
        help="More precise description of the problem")
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        help="Returned product")
    product_returned_quantity = fields.Float(
        string='Quantity',
        digits=(12, 2),
        help="Quantity of product returned")
    unit_sale_price = fields.Float(
        string='Unit sale price',
        digits=(12, 2),
        help="Unit sale price of the product. Auto filled if retrun done "
             "by invoice selection. Be careful and check the automatic "
             "value as don't take into account previous refunds, invoice "
             "discount, can be for 0 if product for free,...")
    return_value = fields.Float(
        compute='_line_total_amount',
        string='Total return',
        help="Quantity returned * Unit sold price")
    prodlot_id = fields.Many2one(
        comodel_name='stock.production.lot',
        string='Serial/Lot n°',
        help="The serial/lot of the returned product")
    applicable_guarantee = fields.Selection(
        selection=[
            ('us', 'Company'),
            ('supplier', 'Supplier'),
            ('brand', 'Brand manufacturer')],
        string='Warranty type')
    guarantee_limit = fields.Date(
        string='Warranty limit',
        readonly=True,
        help="The warranty limit is computed as: invoice date + warranty "
             "defined on selected product.")
    warning = fields.Char(
        string='Warranty',
        readonly=True,
        help="If warranty has expired")
    warranty_type = fields.Selection(
        selection=get_warranty_return_partner,
        string='Warranty type',
        readonly=True,
        help="Who is in charge of the warranty return treatment towards "
             "the end customer. Company will use the current company "
             "delivery or default address and so on for supplier and brand"
             " manufacturer. Does not necessarily mean that the warranty "
             "to be applied is the one of the return partner (ie: can be "
             "returned to the company and be under the brand warranty")
    warranty_return_partner = fields.Many2one(
        comodel_name='res.partner',
        string='Warranty Address',
        help="Where the customer has to send back the product(s)")
    claim_id = fields.Many2one(
        comodel_name='crm.claim',
        string='Related claim',
        help="To link to the case.claim object")
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('refused', 'Refused'),
            ('confirmed', 'Confirmed, waiting for product'),
            ('in_to_control', 'Received, to control'),
            ('in_to_treate', 'Controlled, to treate'),
            ('treated', 'Treated')],
        default='draft',
        string='State')
    substate_id = fields.Many2one(
        comodel_name='substate.substate',
        string='Sub state',
        help="Select a sub state to precise the standard state. Example 1:"
             " state = refused; substate could be warranty over, not in "
             "warranty, no problem,... . Example 2: state = to treate; "
             "substate could be to refund, to exchange, to repair,...")
    last_state_change = fields.Date(
        string='Last change',
        help="To set the last state / substate change")
    invoice_line_id = fields.Many2one(
        comodel_name='account.invoice.line',
        string='Invoice Line',
        help='The invoice line related to the returned product')
    refund_line_id = fields.Many2one(
        comodel_name='account.invoice.line',
        string='Refund Line',
        help='The refund line related to the returned product')
    move_in_id = fields.Many2one(
        comodel_name='stock.move',
        string='Move Line from picking in',
        help='The move line related to the returned product')
    move_out_id = fields.Many2one(
        comodel_name='stock.move',
        string='Move Line from picking out',
        help='The move line related to the returned product')
    location_dest_id = fields.Many2one(
        comodel_name='stock.location',
        string='Return Stock Location',
        help='The return stock location of the returned product')

    @staticmethod
    def warranty_limit(start, warranty_duration):
        """ Take a duration in float, return the duration in relativedelta

        ``relative_delta(months=...)`` only accepts integers.
        We have to extract the decimal part, and then, extend the delta with
        days.

        """
        decimal_part, months = math.modf(warranty_duration)
        months = int(months)
        # If we have a decimal part, we add the number them as days to
        # the limit.  We need to get the month to know the number of
        # days.
        delta = relativedelta(months=months)
        monthday = start + delta
        __, days_month = calendar.monthrange(monthday.year, monthday.month)
        # ignore the rest of the days (hours) since we expect a date
        days = int(days_month * decimal_part)
        return start + relativedelta(months=months, days=days)

    @api.multi
    def _warranty_limit_values(self, invoice,
                               claim_type, product, claim_date):
        if not (invoice and claim_type and product and claim_date):
            return {'guarantee_limit': False, 'warning': False}
        date_invoice = invoice.date_invoice
        if not date_invoice:
            raise InvoiceNoDate
        warning = _(self.WARRANT_COMMENT['not_define'])
        date_invoice = datetime.strptime(date_invoice,
                                         DEFAULT_SERVER_DATE_FORMAT)
        if claim_type == 'supplier':
            suppliers = product.seller_ids
            if not suppliers:
                raise ProductNoSupplier
            supplier = suppliers[0]
            warranty_duration = supplier.warranty_duration
        else:
            warranty_duration = product.warranty
        limit = self.warranty_limit(date_invoice, warranty_duration)
        if warranty_duration > 0:
            claim_date = datetime.strptime(claim_date,
                                           DEFAULT_SERVER_DATETIME_FORMAT)
            if limit < claim_date:
                warning = _(self.WARRANT_COMMENT['expired'])
            else:
                warning = _(self.WARRANT_COMMENT['valid'])
        return {'guarantee_limit': limit.strftime(DEFAULT_SERVER_DATE_FORMAT),
                'warning': warning}

    @api.multi
    def set_warranty_limit(self, claim_line):
        claim = claim_line.claim_id
        invoice = claim.invoice_id
        claim_type = claim.claim_type
        claim_date = claim.date
        product = claim_line.product_id
        try:
            values = self._warranty_limit_values(invoice,
                                                 claim_type, product,
                                                 claim_date)
        except InvoiceNoDate:
            raise orm.except_orm(
                _('Error'),
                _('Cannot find any date for invoice. '
                  'Must be a validated invoice.'))
        except ProductNoSupplier:
                raise orm.except_orm(
                    _('Error'),
                    _('The product has no supplier configured.'))
        self.write(values)
        return True

    @api.multi
    def auto_set_warranty(self):
        """ Set warranty automatically
        if the user has not himself pressed on 'Calculate warranty state'
        button, it sets warranty for him"""
        for line in self:
            if not line.warning:
                line.set_warranty()
        return True

    @api.model
    def get_destination_location(self, product_id,
                                 warehouse_id):
        """Compute and return the destination location ID to take
        for a return. Always take 'Supplier' one when return type different
        from company."""
        prod = False
        if product_id:
            prod_obj = self.env['product.product']
            prod = prod_obj.browse(product_id)
        wh_obj = self.env['stock.warehouse']
        wh = wh_obj.browse(warehouse_id)
        location_dest_id = wh.lot_stock_id.id
        if prod:
            seller = prod.seller_ids
            if seller:
                return_type = seller[0].warranty_return_partner
                if return_type != 'company':
                    location_dest_id = seller[0].name.\
                        property_stock_supplier.id
        return location_dest_id

    @api.multi
    def onchange_product_id(self, product_id, invoice_line_id,
                            claim_id, company_id, warehouse_id,
                            claim_type, claim_date):
        if not claim_id and not (
            company_id and warehouse_id and
                claim_type and claim_date):
            # if we have a claim_id, we get the info from there,
            # otherwise we get it from the args (on creation typically)
            return {}
        if not (product_id and invoice_line_id):
            return {}
        product_obj = self.env['product.product']
        claim_obj = self.env['crm.claim']
        invoice_line_obj = self.env['account.invoice.line']
        claim_line_obj = self.env['claim.line']
        product = product_obj.browse(product_id)
        invoice_line = invoice_line_obj.browse(invoice_line_id)
        invoice = invoice_line.invoice_id

        if claim_id:
            claim = claim_obj.browse(claim_id)
            company = claim.company_id
            warehouse = claim.warehouse_id
            claim_type = claim.claim_type
            claim_date = claim.date
        else:
            warehouse_obj = self.env['stock.warehouse']
            company_obj = self.env['res.company']
            company = company_obj.browse(company_id)
            warehouse = warehouse_obj.browse(warehouse_id)

        values = {}
        try:
            warranty = claim_line_obj._warranty_limit_values(
                invoice,
                claim_type, product,
                claim_date)
        except (InvoiceNoDate, ProductNoSupplier):
            # we don't mind at this point if the warranty can't be
            # computed and we don't want to block the user
            values.update({'guarantee_limit': False, 'warning': False})
        else:
            values.update(warranty)

        warranty_address = claim_line_obj._warranty_return_address_values(
            product, company, warehouse)
        values.update(warranty_address)
        return {'value': values}

    @api.multi
    def _warranty_return_address_values(self, product, company,
                                        warehouse):
        """Return the partner to be used as return destination and
        the destination stock location of the line in case of return.

        We can have various case here:
            - company or other: return to company partner or
              crm_return_address_id if specified
            - supplier: return to the supplier address

        """
        if not (product and company and warehouse):
            return {'warranty_return_partner': False,
                    'warranty_type': False,
                    'location_dest_id': False}
        return_address = None
        seller = product.seller_ids
        if seller:
            return_address_id = seller[0].warranty_return_address.id
            return_type = seller[0].warranty_return_partner
        else:
            # when no supplier is configured, returns to the company
            return_address = (company.crm_return_address_id or
                              company.partner_id)
            return_address_id = return_address.id
            return_type = 'company'
        location_dest_id = self.get_destination_location(
            product.id, warehouse.id)
        return {'warranty_return_partner': return_address_id,
                'warranty_type': return_type,
                'location_dest_id': location_dest_id}

    @api.multi
    def set_warranty_return_address(self, claim_line):
        claim = claim_line.claim_id
        product = claim_line.product_id
        company = claim.company_id
        warehouse = claim.warehouse_id
        values = self._warranty_return_address_values(
            product, company, warehouse)
        self.write(values)
        return True

    @api.multi
    def set_warranty(self):
        """ Calculate warranty limit and address """
        for claim_line in self:
            if not (claim_line.product_id and claim_line.invoice_line_id):
                raise exceptions.Warning(
                    _('Please set product and invoice.'))
            claim_line.set_warranty_limit(claim_line)
            claim_line.set_warranty_return_address(claim_line)
        return True


# TODO add the option to split the claim_line in order to manage the same
# product separately
class CrmClaim(models.Model):
    _inherit = 'crm.claim'

    def init(self, cr):
        cr.execute("""
            UPDATE "crm_claim" SET "number"=id::varchar
            WHERE ("number" is NULL)
               OR ("number" = '/');
        """)

    @api.model
    def _get_sequence_number(self):
        seq_obj = self.env['ir.sequence']
        res = seq_obj.get('crm.claim.rma') or '/'
        return res

    @api.model
    def _get_default_warehouse(self):
        user_obj = self.env['res.users']
        user = user_obj.browse(self.env.uid)
        company_id = user.company_id.id
        wh_obj = self.env['stock.warehouse']
        wh_ids = wh_obj.search([('company_id', '=', company_id)])
        if not wh_ids:
            raise orm.except_orm(
                _('Error!'),
                _('There is no warehouse for the current user\'s company.'))
        return wh_ids[0]

    @api.multi
    def name_get(self):
        res = []
        for claim in self:
            number = claim.number and str(claim.number) or ''
            res.append((claim.id, '[' + number + '] ' + claim.name))
        return res

    @api.model
    def create(self, vals):
        if ('number' not in vals) or (vals.get('number') == '/'):
            vals['number'] = self._get_sequence_number()
        new_id = super(CrmClaim, self).create(vals)
        return new_id

    @api.multi
    def copy_data(self, default=None):
        if default is None:
            default = {}
        self.ensure_one()
        std_default = {
            'invoice_ids': False,
            'picking_ids': False,
            'number': self._get_sequence_number(),
        }
        std_default.update(default)
        return super(CrmClaim, self).copy_data(default=std_default)

    number = fields.Char(
        string='Number',
        readonly=True,
        required=True,
        select=True,
        default='/',
        help="Company internal claim unique number")
    claim_type = fields.Selection(
        selection=[
            ('customer', 'Customer'),
            ('supplier', 'Supplier'),
            ('other', 'Other')],
        string='Claim type',
        required=True,
        default='customer',
        help="Customer: from customer to company.\n "
             "Supplier: from company to supplier.")
    claim_line_ids = fields.One2many(
        comodel_name='claim.line',
        inverse_name='claim_id',
        string='Return lines')
    planned_revenue = fields.Float(string='Expected revenue')
    planned_cost = fields.Float(string='Expected cost')
    real_revenue = fields.Float(string='Real revenue')
    real_cost = fields.Float(string='Real cost')
    invoice_ids = fields.One2many(
        comodel_name='account.invoice',
        inverse_name='claim_id',
        string='Refunds')
    picking_ids = fields.One2many(
        comodel_name='stock.picking',
        inverse_name='claim_id',
        string='RMA')
    invoice_id = fields.Many2one(
        comodel_name='account.invoice',
        string='Invoice',
        help='Related original Cusotmer invoice')
    delivery_address_id = fields.Many2one(
        comodel_name='res.partner',
        string='Partner delivery address',
        help="This address will be used to deliver repaired or replacement"
             "products.")
    warehouse_id = fields.Many2one(
        comodel_name='stock.warehouse',
        string='Warehouse',
        default=_get_default_warehouse,
        required=True)

    _sql_constraints = [
        ('number_uniq', 'unique(number, company_id)',
         'Number/Reference must be unique per Company!'),
    ]

    @api.v7
    def onchange_invoice_id(self, cr, uid, ids, invoice_id, warehouse_id,
                            claim_type, claim_date, company_id, lines,
                            create_lines=False, context=None):
        invoice_line_obj = self.pool.get('account.invoice.line')
        invoice_obj = self.pool.get('account.invoice')
        product_obj = self.pool['product.product']
        claim_line_obj = self.pool.get('claim.line')
        company_obj = self.pool['res.company']
        warehouse_obj = self.pool['stock.warehouse']
        invoice_line_ids = invoice_line_obj.search(
            cr, uid,
            [('invoice_id', '=', invoice_id)],
            context=context)
        claim_lines = []
        value = {}
        if not warehouse_id:
            warehouse_id = self._get_default_warehouse(cr, uid,
                                                       context=context)
        invoice_lines = invoice_line_obj.browse(cr, uid, invoice_line_ids,
                                                context=context)

        def warranty_values(invoice, product):
            values = {}
            try:
                warranty = claim_line_obj._warranty_limit_values(
                    cr, uid, [], invoice,
                    claim_type, product,
                    claim_date, context=context)
            except (InvoiceNoDate, ProductNoSupplier):
                # we don't mind at this point if the warranty can't be
                # computed and we don't want to block the user
                values.update({'guarantee_limit': False, 'warning': False})
            else:
                values.update(warranty)
            company = company_obj.browse(cr, uid, company_id, context=context)
            warehouse = warehouse_obj.browse(cr, uid, warehouse_id,
                                             context=context)
            warranty_address = claim_line_obj._warranty_return_address_values(
                cr, uid, [], product, company,
                warehouse, context=context)
            values.update(warranty_address)
            return values

        if create_lines:  # happens when the invoice is changed
            for invoice_line in invoice_lines:
                location_dest_id = claim_line_obj.get_destination_location(
                    cr, uid, invoice_line.product_id.id,
                    warehouse_id, context=context)
                line = {
                    'name': invoice_line.name,
                    'claim_origine': "none",
                    'invoice_line_id': invoice_line.id,
                    'product_id': invoice_line.product_id.id,
                    'product_returned_quantity': invoice_line.quantity,
                    'unit_sale_price': invoice_line.price_unit,
                    'location_dest_id': location_dest_id,
                    'state': 'draft',
                }
                line.update(warranty_values(invoice_line.invoice_id,
                                            invoice_line.product_id))
                claim_lines.append(line)
        elif lines:
            # happens when the date, warehouse or claim type is
            # modified
            for command in lines:
                code = command[0]
                # assert code != 6, "command 6 not supported in on_change"
                if code in (0, 1, 4):
                    # 0: link a new record with values
                    # 1: update an existing record with values
                    # 4: link to existing record
                    line_id = command[1]
                    if code == 4:
                        code = 1  # we want now to update values
                        values = {}
                    else:
                        values = command[2]
                    invoice_line_id = values.get('invoice_line_id')
                    product_id = values.get('product_id')
                    if code == 1:  # get the existing line
                        # if the fields have not changed, fallback
                        # on the database values
                        browse_line = claim_line_obj.read(cr, uid,
                                                          line_id,
                                                          ['invoice_line_id',
                                                           'product_id'],
                                                          context=context)
                        if not invoice_line_id:
                            invoice_line_id = browse_line['invoice_line_id'][0]
                        if not product_id:
                            product_id = browse_line['product_id'][0]

                    if invoice_line_id and product_id:
                        invoice_line = invoice_line_obj.browse(cr, uid,
                                                               invoice_line_id,
                                                               context=context)
                        product = product_obj.browse(cr, uid, product_id,
                                                     context=context)
                        values.update(warranty_values(invoice_line.invoice_id,
                                                      product))
                    claim_lines.append((code, line_id, values))
                elif code in (2, 3, 5):
                    claim_lines.append(command)

        value = {'claim_line_ids': claim_lines}
        delivery_address_id = False
        if invoice_id:
            invoice = invoice_obj.browse(cr, uid, invoice_id, context=context)
            delivery_address_id = invoice.partner_id.id
        value['delivery_address_id'] = delivery_address_id

        return {'value': value}

    @api.multi
    def message_get_reply_to(self):
        """ Override to get the reply_to of the parent project. """
        return [claim.section_id.message_get_reply_to()[0]
                if claim.section_id else False
                for claim in self]

    @api.multi
    def message_get_suggested_recipients(self):
        recipients = super(CrmClaim, self
                           ).message_get_suggested_recipients()
        try:
            for claim in self:
                if claim.partner_id:
                    self._message_add_suggested_recipient(
                        recipients, claim,
                        partner=claim.partner_id, reason=_('Customer'))
                elif claim.email_from:
                    self._message_add_suggested_recipient(
                        recipients, claim,
                        email=claim.email_from, reason=_('Customer Email'))
        except (osv.except_osv, orm.except_orm):
            # no read access rights -> just ignore suggested recipients
            # because this imply modifying followers
            pass
        return recipients
