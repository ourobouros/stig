# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details
# http://www.gnu.org/licenses/gpl-3.0.txt

from ..logging import make_logger
log = make_logger(__name__)

from .settings import (ValueBase, StringValue, IntegerValue, NumberValue,
                       BooleanValue, PathValue, ListValue, SetValue,
                       OptionValue)
from ..client.errors import ClientError
from ..client import constants as const
from ..client import convert


class SrvValueBase(ValueBase):
    def __init__(self, name, getter, setter, description='No description available'):
        super().__init__(name, default=const.DISCONNECTED, description=description)
        self._getter = getter
        self._setter = setter

    @property
    def value(self):
        return self._getter()

    async def set(self, value):
        log.debug('Setting server value {!r}: {!r}'.format(self.name, value))
        try:
            value = self.convert(value)
            self.validate(value)
            await self._setter(value)
        except ClientError as e:
            raise ValueError("Can't change server setting {}: {}".format(self.name, e))
        except ValueError as e:
            log.debug('{} while setting {} to {!r}: {}'
                      .format(type(e).__name__, self.name, value, e))
            raise ValueError('{} = {}: {}'.format(self.name, self.str(value), e))
        else:
            log.debug('Successfully set {} to {!r}'
                      .format(self.name, value))

    def convert(self, value):
        log.debug('SrvValueBase: converting {!r}'.format(value))
        if value is const.DISCONNECTED:
            return value
        else:
            log.debug('consulting super().convert for {!r}'.format(value))
            value = super().convert(value)
            log.debug('got back: {!r}'.format(value))
            return value

    def validate(self, value):
        log.debug('SrvValueBase: validating {!r}'.format(value))
        if value is not const.DISCONNECTED:
            log.debug('SrvValueBase: consulting super().validate for {!r}'.format(value))
            super().validate(value)
            log.debug('Valid value: {!r}'.format(value))


class RateLimitSrvValue(SrvValueBase, NumberValue):
    typename = 'number or bool'
    valuesyntax = '[+=|-=]<NUMBER>[k|M|G|T|Ki|Mi|Gi|Ti][b|B] or [on|off]'

    def convert(self, value):
        log.debug('RateLimitValue: converting {!r}'.format(value))
        try:
            # value may be something like 'on' or 'off'
            value = BooleanValue.convert(self, value)
        except ValueError:
            log.debug('Not a bool: {!r}'.format(value))

            # Parse relative values
            if isinstance(value, str) and len(value) >= 3 and value[:2] in ('+=', '-='):
                op = value[:2]
                num = convert.bandwidth(value[2:].strip())
                if self.value is const.UNLIMITED and op == '+=':
                    # Act as if current value were 0 because values >= 0 are UNLIMITED.
                    return num
                return super().convert(op + str(float(num)))

            # Parse other strings or numbers
            elif not isinstance(value, const.Constant):
                return convert.bandwidth(value)

            # Let parent provide the error message
            return super().convert(value)
        else:
            # Rate limit is either enabled or disabled
            log.debug('Rate limit is either turned {}'.format('on' if value else 'off'))
            return const.ENABLED if value else const.DISABLED

    def validate(self, value):
        if value not in (const.ENABLED, const.DISABLED):
            try:
                super().validate(value)
            except ValueError as e:
                raise ValueError('{!r}'.format(e))


class PathSrvValue(SrvValueBase, PathValue):
    pass


def is_server_setting(name):
    if name.startswith('srv.') and \
       not name.startswith('srv.timeout') and \
       not name.startswith('srv.url'):
        return True
    else:
        return False
