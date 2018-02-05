# -*- coding: utf-8 -*-
#
# This file is part of cepces.
#
# cepces is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# cepces is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with cepces.  If not, see <http://www.gnu.org/licenses/>.
#
from cepces import Base as CoreBase
from cepces.krb5 import types as ktypes
from cepces.krb5 import functions as kfuncs
import ctypes
import re

# Regular expressions for matching against keytab and principal names.
NAME_EX = '^(?:(?P<type>[A-Z]+):)?(?P<residual>.+)$'
PRINCIPAL_EX = '^(?P<primary>[^/]+)(?:/(?P<instance>.+))?@(?P<realm>.+)$'


class Base(CoreBase):
    def __init__(self, handle):
        super().__init__()

        self._logger.debug("Handle {}".format(handle))
        self._handle = handle

    @property
    def handle(self):
        if hasattr(self, '_handle'):
            return self._handle
        else:
            return None


class Context(Base):
    def __init__(self):
        super().__init__(ktypes.krb5_context())

        kfuncs.init_context(self.handle)

    def __del__(self):
        if self.handle:
            self._logger.debug("Freeing context {}".format(self.handle))
            kfuncs.free_context(self.handle)


class KeytabName(Base):
    def __init__(self, name=None, context=None, keytab=None, normalize=True):
        """Represents the name of the keytab.

        MIT Kerberos represents this as 'TYPE:RESIDUAL' (e.g.,
        'FILE:/etc/krb5.keytab'). Heimdall on the other hand, retreiving the
        name of the keytab only returns the residual (e.g.,
        '/etc/krb5.keytab').

        Setting normalize to True constructs a 'TYPE:RESIDUAL' name, even if
        the native call to krb5_kt_get_name only returns the residual part.
        """
        if name and context and keytab:
            raise RuntimeError("Only specify name OR context and keytab.")
        elif name:
            self._init_name(name)
        elif context and keytab:
            self._init_keytab(context, keytab, normalize)
        else:
            # Raise an error.
            raise RuntimeError("Missing name OR context and keytab.")

    def __str__(self):
        return self._name

    def _init_name(self, name):
        parts = self.split(':', maxsplit=1)

        if not len(parts) == 2:
            raise RuntimeError("Name has to equal \"TYPE:RESIDUAL\".")

        self._name = name
        self._type = parts[0]
        self._residual = parts[1]

    def _init_keytab(self, context, keytab, normalize):
        s = ctypes.create_string_buffer(ktypes.LINE_MAX)

        kfuncs.kt_get_name(
            context.handle,
            keytab.handle,
            s,
            ktypes.LINE_MAX,
        )

        name = s.value.decode('utf-8')
        match = re.match(NAME_EX, name)

        self._type = match.group('type')
        self._residual = match.group('residual')

        if not self._type:
            s = kfuncs.kt_get_type(
                context.handle,
                keytab.handle,
            )

            # If type is still None, assume that it's 'FILE'.
            if s:
                self._type = s.decode('utf-8')
            else:
                self._type = 'FILE'

            if normalize:
                self._name = '{}:{}'.format(self._type, self._residual)
            else:
                self._name = self._risidual
        else:
            self._name = name

    @property
    def type(self):
        return self._type

    @property
    def residual(self):
        return self._residual

    @staticmethod
    def default(context):
        s = ctypes.create_string_buffer(ktypes.LINE_MAX)

        kfuncs.kt_default_name(
            context.handle,
            s,
            ktypes.LINE_MAX,
        )

        return s.value.decode('utf-8')


class Keytab(Base):
    def __init__(self, context, keytab=None):
        super().__init__(ktypes.krb5_keytab())

        self._context = context
        self._keytab = keytab

        if self._keytab:
            kfuncs.kt_resolve(
                self._context.handle,
                self._keytab.encode('utf-8'),
                self.handle,
            )
        else:
            kfuncs.kt_default(
                self._context.handle,
                self.handle,
            )

        self._name = KeytabName(context=self._context, keytab=self)

    def __del__(self):
        if self.handle:
            self._logger.debug("Closing keytab {}".format(self.handle))
            kfuncs.kt_close(self._context.handle, self.handle)

    def __str__(self):
        return str(self._name)

    @property
    def type(self):
        return self._name.type

    @property
    def residual(self):
        return self._name.residual


class PrincipalName(Base):
    def __init__(self, principal, name, context, host, service, service_type):
        if name:
            kfuncs.parse_name(
                context.handle,
                name.encode('utf-8'),
                principal.handle,
            )
        else:
            kfuncs.sname_to_principal(
                context.handle,
                host,
                service,
                service_type,
                principal.handle,
            )

        # Unparse the recently acquired principal to retrieve the different
        # components.
        s = ctypes.c_char_p()
        kfuncs.unparse_name(context.handle, principal.handle, s)
        name = s.value.decode('utf-8')
        kfuncs.free_unparsed_name(context.handle, s)

        match = re.match(PRINCIPAL_EX, name)

        self._primary = match.group('primary')
        self._instance = match.group('instance')
        self._realm = match.group('realm')

    @property
    def primary(self):
        return self._primary

    @property
    def instance(self):
        return self._instance

    @property
    def realm(self):
        return self._realm


class Principal(Base):
    def __init__(self, context, name=None, host=None, service=None,
                 service_type=ktypes.PrincipalType.KRB5_NT_SRV_HST):
        super().__init__(ktypes.krb5_principal())

        self._context = context
        self._name = PrincipalName(
            self,
            name,
            context,
            host,
            service,
            service_type,
        )

    def __del__(self):
        if self.handle:
            self._logger.debug("Freeing principal {}".format(self.handle))
            kfuncs.free_principal(self._context.handle, self.handle)

    @property
    def primary(self):
        return self._name.primary

    @property
    def instance(self):
        return self._name.instance

    @property
    def realm(self):
        return self._name.realm


class CredentialOptions(Base):
    def __init__(self, context):
        super().__init__(ktypes.krb5_get_init_creds_opt_p())

        self._context = context
        self._forwardable = False
        self._encryption_types = []

        kfuncs.get_init_creds_opt_alloc(
            self._context.handle,
            self.handle,
        )

    def __del__(self):
        if self.handle:
            self._logger.debug("Freeing credential options {}".format(
                self.handle))
            kfuncs.get_init_creds_opt_free(self._context.handle, self.handle)

    @property
    def forwardable(self):
        return self._forwardable

    @forwardable.setter
    def forwardable(self, forward):
        kfuncs.get_init_creds_opt_set_forwardable(
            self.handle,
            int(self.forwardable is True)
        )

        self._forwardable = True

    @property
    def encryption_types(self):
        return self._encryption_types

    @encryption_types.setter
    def encryption_types(self, types):
        if not types:
            return

        etypes = (ktypes.krb5_enctype * len(types))(*types)

        kfuncs.get_init_creds_opt_set_etype_list(
            self.handle,
            ctypes.cast(etypes, ctypes.POINTER(ktypes.krb5_enctype)),
            len(types),
        )

        self._encryption_types = types


class Credentials(Base):
    def __init__(self, context, client, keytab, start_time, tkt_service,
                 options):
        super().__init__(ktypes.krb5_creds())

        self._context = context
        self._client = client
        self._keytab = keytab
        self._start_time = start_time
        self._tkt_service = tkt_service
        self._options = options
        self._init()

    def _init(self):
        kfuncs.get_init_creds_keytab(
            self._context.handle,
            self.handle,
            self._client.handle,
            self._keytab.handle,
            self._start_time,
            self._tkt_service.encode('utf-8'),
            self._options.handle,
        )

    def __del__(self):
        if self.handle:
            self._logger.debug("Freeing credentials {}".format(
                self.handle))
            kfuncs.free_cred_contents(self._context.handle, self.handle)


class CredentialCache(Base):
    def __init__(self, context, name, client, credentials):
        super().__init__(ktypes.krb5_ccache())

        self._context = context
        self._name = name
        self._client = client
        self._credentials = credentials

        kfuncs.cc_resolve(
            self._context.handle,
            self._name.encode('utf-8'),
            self.handle,
        )

        kfuncs.cc_initialize(
            self._context.handle,
            self.handle,
            self._client.handle,
        )

        kfuncs.cc_store_cred(
            self._context.handle,
            self.handle,
            self._credentials.handle,
        )

    def __del__(self):
        if self.handle:
            self._logger.debug("Closing credential cache {}".format(
                self.handle))
            kfuncs.krb5_cc_close(self._context.handle, self.handle)
