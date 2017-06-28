from __future__ import unicode_literals

import csv
import os
import uuid as uuid

from django.conf import settings
from django.contrib.auth import models as admin_models
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Avg, F
from django.utils import timezone

from app.emails import sendgrid_send, MailListManager
from app.utils import reverse

# Votes weight
TECH_WEIGHT = 0.2
PERSONAL_WEIGHT = 0.8

# Reimbursement tiers
DEFAULT_REIMBURSEMENT = 100

APP_PENDING = 'P'
APP_REJECTED = 'R'
APP_INVITED = 'I'
APP_LAST_REMIDER = 'LR'
APP_CONFIRMED = 'C'
APP_CANCELLED = 'X'
APP_ATTENDED = 'A'
APP_EXPIRED = 'E'

STATUS = [
    (APP_PENDING, 'Pending'),
    (APP_REJECTED, 'Rejected'),
    (APP_INVITED, 'Invited'),
    (APP_LAST_REMIDER, 'Last reminder'),
    (APP_CONFIRMED, 'Confirmed'),
    (APP_CANCELLED, 'Cancelled'),
    (APP_ATTENDED, 'Attended'),
    (APP_EXPIRED, 'Expired'),
]

MALE = 'M'
FEMALE = 'F'
NON_BINARY = 'NB'

GENDERS = [
    (MALE, 'Male'),
    (FEMALE, 'Female'),
    (NON_BINARY, 'Non-binary'),
]

CURRENT_EDITION = 'F17'

EDITIONS = [
    (CURRENT_EDITION, settings.CURRENT_EDITION)
]

D_NONE = 'None'
D_VEGETERIAN = 'Vegeterian'
D_GLUTEN_FREE = 'Gluten-free'

DIETS = [
    (D_NONE, 'None'),
    (D_VEGETERIAN, 'Vegeterian'),
    (D_GLUTEN_FREE, 'Gluten free')
]

TSHIRT_SIZES = [(size, size) for size in ('XS S M L XL'.split(' '))]


# Create your models here.

def calculate_reimbursement(country):
    with open(os.path.join(settings.BASE_DIR, 'reimbursements.csv')) as reimbursements:
        reader = csv.reader(reimbursements, delimiter=',')
        for row in reader:
            if country in row[0]:
                return int(row[1])

    return DEFAULT_REIMBURSEMENT


class Hacker(models.Model):
    """
    Year agnostic hacker fields
    """
    user = models.OneToOneField(admin_models.User)
    name = models.CharField(max_length=250)
    lastname = models.CharField(max_length=250)
    gender = models.CharField(max_length=20, blank=True, null=True, choices=GENDERS)

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)

    # University
    graduation_year = models.IntegerField(choices=[(year, str(year)) for year in range(2016, 2020)])
    university = models.CharField(max_length=300)
    degree = models.CharField(max_length=300)

    # URLs
    github = models.URLField(blank=True, null=True)
    devpost = models.URLField(blank=True, null=True)
    linkedin = models.URLField(blank=True, null=True)
    site = models.URLField(blank=True, null=True)

    # Info for swag and food
    diet = models.CharField(max_length=300, choices=DIETS)
    tshirt_size = models.CharField(max_length=3, default='M', choices=TSHIRT_SIZES)


class Application(models.Model):
    # We are pointing to hacker because we need to have that information. If you don't, you can't apply.
    hacker = models.ForeignKey(Hacker, null=False)

    edition = models.CharField(max_length=7, choices=EDITIONS, default=CURRENT_EDITION)

    # Meta fields
    id = models.CharField(max_length=300, primary_key=True)
    # When was the application completed
    submission_date = models.DateTimeField()
    # When was the last status update
    status_update_date = models.DateTimeField(blank=True, null=True)
    # Internal SendGrid ID
    sendgrid_id = models.CharField(max_length=300, blank=True, null=True)

    # Personal data (asking here because we don't want to ask birthday)
    under_age = models.NullBooleanField()

    # About you
    first_timer = models.NullBooleanField()
    # Why do you want to come to X?
    description = models.CharField(max_length=500)
    # Explain a little bit what projects have you done lately
    projects = models.CharField(max_length=500)

    # Reimbursement
    scholarship = models.NullBooleanField()
    reimbursement_money = models.IntegerField(blank=True, null=True)
    origin_city = models.CharField(max_length=300)
    origin_country = models.CharField(max_length=300)

    lennyface = models.CharField(max_length=300, default='-.-')
    resume = models.URLField(blank=True, null=True)

    # Team
    team = models.NullBooleanField()
    teammates = models.CharField(max_length=300, blank=True, null=True)

    # Needs to be set to true -> else rejected
    authorized_mlh = models.NullBooleanField()
    status = models.CharField(choices=STATUS, default=APP_PENDING, max_length=2)

    invited_by = models.ForeignKey(admin_models.User, null=True, blank=True)

    # TODO: TEAM EXTERNAL

    def __repr__(self):
        return self.hacker.name + ' ' + self.hacker.lastname

    def invite(self, user):

        # We can re-invite someone invited
        if self.status in [APP_CONFIRMED, APP_ATTENDED]:
            raise ValidationError('Application has already answered invite. Current status: %s' % self.status)
        # if self.status == APP_INVITED:
        #     self._send_invite(request, mail_title="[HackUPC] Missing answer")
        # else:
        #     self._send_invite(request)
        self.status = APP_INVITED
        self.invited_by = user
        self.last_invite = timezone.now()
        self.last_reminder = None
        self.status_update_date = timezone.now()
        self.save()

    def last_reminder(self):
        if self.status != APP_INVITED:
            raise ValidationError('Reminder can\'t be sent to non-pending applications')
        self.status_update_date = timezone.now()
        self.status = APP_LAST_REMIDER
        self.save()

    def expire(self):
        self.status_update_date = timezone.now()
        self.status = APP_EXPIRED
        self.save()

    def reject(self, request):
        if not request.user.has_perm('register.invite'):
            raise ValidationError('User doesn\'t have permission to invite user')
        if self.status == APP_ATTENDED:
            raise ValidationError('Application has already attended. Current status: %s' % self.status)
        self.status = APP_REJECTED
        self.status_update_date = timezone.now()
        self.save()

    def is_confirmed(self):
        return self.status == APP_CONFIRMED

    def is_cancelled(self):
        return self.status == APP_CANCELLED

    def answered_invite(self):
        return self.status in [APP_CONFIRMED, APP_CANCELLED, APP_ATTENDED]

    def is_pending(self):
        return self.status == APP_PENDING

    def is_invited(self):
        return self.status == APP_INVITED

    def is_expired(self):
        return self.status == APP_EXPIRED

    def is_rejected(self):
        return self.status == APP_REJECTED


    def is_last_reminder(self):
        return self.status == APP_LAST_REMIDER

    def can_be_cancelled(self):
        return self.status == APP_CONFIRMED or self.status == APP_INVITED or self.status == APP_LAST_REMIDER

    def send_reimbursement(self, request):
        if self.status != APP_INVITED and self.status != APP_CONFIRMED:
            raise ValidationError('Application can\'t be reimbursed as it hasn\'t been invited yet')
        if not self.scholarship:
            raise ValidationError('Application didn\'t ask for reimbursement')
        if not self.reimbursement_money:
            self.reimbursement_money = calculate_reimbursement(self.origin_country)

        self._send_reimbursement(request)
        self.save()

    def confirm(self):
        if self.status == APP_CANCELLED:
            raise ValidationError('This invite has been cancelled.')
        elif self.status == APP_EXPIRED:
            raise ValidationError('Unfortunately your invite has expired.')
        elif self.status in [APP_INVITED, APP_LAST_REMIDER]:
            self.status = APP_CONFIRMED
            self.status_update_date = timezone.now()
            self.save()
            if settings.MAIL_LISTS_ENABLED:
                m = MailListManager()
                m.add_applicant_to_list(self, m.W17_GENERAL_LIST_ID)
        elif self.status == APP_CONFIRMED:
            return None
        else:
            raise ValidationError('Unfortunately his application hasn\'t been invited [yet]')

    def cancel(self):
        if not self.can_be_cancelled():
            raise ValidationError('Application can\'t be cancelled. Current status: %s' % self.status)
        if self.status != APP_CANCELLED:
            self.status = APP_CANCELLED
            self.status_update_date = timezone.now()
            self.save()
            if settings.MAIL_LISTS_ENABLED:
                m = MailListManager()
                m.remove_applicant_from_list(self, m.W17_GENERAL_LIST_ID)

    def confirmation_url(self, request=None):
        return reverse('confirm_app', kwargs={'token': self.id}, request=request)

    def cancelation_url(self, request=None):
        return reverse('cancel_app', kwargs={'token': self.id}, request=request)

    def check_in(self):
        self.status = APP_ATTENDED
        self.status_update_date = timezone.now()
        self.save()

    def _send_reimbursement(self, request):
        sendgrid_send(
            [self.hacker.user.email],
            "[HackUPC] Reimbursement granted",
            {'%name%': self.hacker.name,
             '%token%': self.id,
             '%money%': self.reimbursement_money,
             '%country%': self.origin_country,
             '%confirmation_url%': self.confirmation_url(request),
             '%cancellation_url%': self.cancelation_url(request)},
            '06d613dd-cf70-427b-ae19-6cfe7931c193',
            from_email='HackUPC Reimbursements Team <reimbursements@hackupc.com>'
        )

    class Meta:
        permissions = (
            ("invite", "Can invite applications"),
            ("vote", "Can review applications"),
            ("checkin", "Can check-in applications"),
            ("reject", "Can reject applications"),
            ("ranking", "Can view voting ranking"),
        )
        unique_together = ("hacker", "edition")


VOTES = (
    (1, '1'),
    (2, '2'),
    (3, '3'),
    (4, '4'),
    (5, '5'),
    (6, '6'),
    (7, '7'),
    (8, '8'),
    (9, '9'),
    (10, '10'),
)


class Vote(models.Model):
    application = models.ForeignKey(Application)
    user = models.ForeignKey(admin_models.User)
    tech = models.IntegerField(choices=VOTES, null=True)
    personal = models.IntegerField(choices=VOTES, null=True)
    calculated_vote = models.FloatField(null=True)

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        """
        We are overriding this in order to standarize each review vote with the new vote.
        Also we store a calculated vote for each vote so that we don't need to do it later.

        Thanks to Django awesomeness we do all the calculations with only 3 queries to the database.
        2 selects and 1 update. The performance is way faster than I thought. If improvements need to be done
        using a better DB than SQLite should increase performance. As long as the database can handle aggregations
        efficiently this will be good.

        By casassg
        """
        super(Vote, self).save(force_insert, force_update, using, update_fields)

        # only recalculate when values are different than None
        if not self.personal or not self.tech:
            return

        # Retrieve averages
        avgs = admin_models.User.objects.filter(id=self.user_id).aggregate(tech=Avg('vote__tech'),
                                                                           pers=Avg('vote__personal'))
        p_avg = round(avgs['pers'], 2)
        t_avg = round(avgs['tech'], 2)

        # Calculate standard deviation for each scores
        sds = admin_models.User.objects.filter(id=self.user_id).aggregate(
            tech=Avg((F('vote__tech') - t_avg) * (F('vote__tech') - t_avg)),
            pers=Avg((F('vote__personal') - p_avg) * (F('vote__personal') - p_avg)))

        # Alternatively, if standard deviation is 0.0, set it as 1.0 to avoid division by 0.0 in the update statement
        p_sd = round(sds['pers'], 2) or 1.0
        t_sd = round(sds['tech'], 2) or 1.0

        # Apply standarization. Standarization formula:
        # x(new) = (x - u)/o
        # where u is the mean and o is the standard deviation
        #
        # See this: http://www.dataminingblog.com/standardization-vs-normalization/
        Vote.objects.filter(user=self.user).update(
            calculated_vote=
            PERSONAL_WEIGHT * (F('personal') - p_avg) / p_sd +
            TECH_WEIGHT * (F('tech') - t_avg) / t_sd
        )

    class Meta:
        unique_together = ('application', 'user')
