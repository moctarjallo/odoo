from datetime import datetime

from odoo.addons.event.tests.common import EventCase
from odoo.addons.mail.tests.common import MockEmail
from odoo.tests import Form, tagged, users
from odoo.tools import formataddr


@tagged("event_mail", "mail_template", "post_install", "-at_install")
class TestMailing(EventCase, MockEmail):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # freeze some datetimes, and ensure more than 1D+1H before event starts
        # to ease time-based scheduler check
        # Since `now` is used to set the `create_date` of an event and create_date
        # has often microseconds, we set it to ensure that the scheduler we still be
        # launched if scheduled_date == create_date - microseconds
        cls.reference_now = datetime(2024, 7, 20, 14, 30, 15, 123456)
        cls.event_date_begin = datetime(2024, 7, 22, 8, 0, 0)
        cls.event_date_end = datetime(2024, 7, 24, 18, 0, 0)
        with cls.mock_datetime_and_now(cls, cls.reference_now):
            cls.test_event = cls.env['event.event'].create({
                'date_begin': cls.event_date_begin,
                'date_end': cls.event_date_end,
                'date_tz': 'Europe/Brussels',
                'event_mail_ids': False,
                'name': 'TestEvent',
            })
            cls.registrations = cls.env["event.registration"].create([
                {
                    "event_id": cls.test_event.id,
                    "partner_id": cls.event_customer.id,
                },
                {
                    "event_id": cls.test_event.id,
                    "partner_id": cls.event_customer2.id,
                },
                {
                    "email": "robodoo@example.com",
                    "event_id": cls.test_event.id,
                    "name": "Robodoo",
                },
            ])

    @users("user_eventuser")
    def test_event_mail_attendees(self):
        template_form = Form(
            self.env["mail.template"].with_context(default_model="event.registration", default_name="Test Template")
        )
        template = template_form.save()
        event = self.test_event.with_user(self.env.user)
        event.write({
            'event_mail_ids': [
                (0, 0, {
                    'interval_type': 'before_event',
                    'interval_nbr': 0,
                    'template_ref': f'mail.template,{template.id}',
                })
            ]
        })

        for event_values, exp_mail_values in [
            (
                {"organizer_id": self.event_organizer.id, "user_id": self.user_eventmanager.id},
                {"email_from": self.event_organizer.email_formatted},
            ),
            (
                {"organizer_id": False},
                {"email_from": self.user_eventmanager.company_id.email_formatted},
            ),
            (
                {"company_id": False},
                {"email_from": self.user_eventuser.email_formatted},
            ),
        ]:
            with self.subTest(event_values=event_values):
                event.write(event_values)
                with self.mock_mail_gateway(), self.mock_datetime_and_now(self.event_date_begin):
                    event.event_mail_ids._send_mail(self.registrations)

                self.assertMailMailWEmails(
                    [
                        self.event_customer.email_formatted,
                        self.event_customer2.email_formatted,
                        formataddr(("Robodoo", "robodoo@example.com")),
                    ],
                    "outgoing",
                    fields_values=exp_mail_values,
                )

    @users("user_eventuser")
    def test_mail_template_creation(self):
        """ Check default values when creating registration templates, should
        be correctly configured by default. """
        template_form_default = Form(
            self.env["mail.template"].with_context(default_model="event.registration")
        )
        template_form_user = Form(self.env["mail.template"])
        template_form_user.model_id = self.env["ir.model"]._get("event.registration")

        for template in (template_form_default, template_form_user):
            self.assertEqual(
                template.email_from,
                "{{ (object.event_id.organizer_id.email_formatted or object.event_id.company_id.email_formatted or user.email_formatted or '') }}"
            )
            self.assertEqual(
                template.email_to,
                "{{ (object.email and format_addr((object.name, object.email)) or object.partner_id.email_formatted or '') }}",
            )
            self.assertEqual(
                template.lang,
                "{{ object.event_id.lang or object.partner_id.lang }}",
            )
            self.assertFalse(template.use_default_to)
