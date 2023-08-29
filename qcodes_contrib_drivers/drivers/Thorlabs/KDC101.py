# -*- coding: utf-8 -*-
"""QCoDes-Driver for Thorlab KDC101 K-Cube Brushed DC Servo Motor Controller
https://www.thorlabs.com/thorproduct.cfm?partnumber=KDC101

Authors:
    Julien Barrier, <julien@julienbarrier.eu>
"""
import os
import sys
import ctypes
import logging
from typing import Any
from time import sleep, time

from qcodes.instrument import Instrument
from qcodes.parameters import Parameter
from qcodes import validators as vals

from .private import ConnexionErrors, GeneralErrors, MotorErrors

log = logging.getLogger(__name__)

class Thorlabs_KDC101(Instrument):
    """Instrument driver for the Thorlabs KDC101 servo motor controller

    Args:
        Instrument (_type_): _description_
    """
    _CONDITIONS = ['homed', 'moved', 'stopped', 'limit_updated']
    def __init__(self,
                 name: str,
                 serial_number: str,
                 simulation: bool = False,
                 polling: int = 200,
                 home: bool = False,
                 **kwargs):
        super().__init__(name, **kwargs)
        self.serial_number = serial_number
        self._serial_number = ctypes.c_char_p(self.serial_number.encode('ascii'))
        if sys.platform != 'win32':
            self._dll: Any = None
            raise OSError('Thorlabs Kinesis only works on Windows')
        else:
            os.add_dll_directory(r'C:\Program Files\Thorlabs\Kinesis')
            self._dll_path = 'Thorlabs.MotionControl.KCube.DCServo.dll'
            self._dll = ctypes.cdll.LoadLibrary(self._dll_path)

        self._simulation = simulation
        if self._simulation:
            self.enable_simulation()

        if self._dll.TLI_BuildDeviceList() == 0:
            self._dll.CC_Open(self._serial_number)
            self._start_polling(polling)

        self._info = self._get_hardware_info()
        self.model = self._info[0].decode('utf-8')
        self.version = self._info[4]

        self._device_info = dict(zip(
            ['type_ID', 'description', 'PID', 'is_known_type', 'motor_type',
             'is_piezo', 'is_laser', 'is_custom', 'is_rack', 'max_channels'],
            self._get_device_info()))

        self._load_settings()
        self._set_limits_approach(1)

        sleep(3)

        self._clear_message_queue()

        if home:
            if not self._can_home():
                self.homed = False
                raise RuntimeError('Device `{}` is not homeable')
            else:
                self.go_home()
        else:
            self.homed = False


        self.position = Parameter(
            'position',
            label='Position',
            get_cmd=self._get_position,
            set_cmd=self._set_position,
            vals=vals.Numbers(),
            unit='\u00b0',
            instrument=self
        )

        self.max_position = Parameter(
            'max_position',
            label='Maximum position',
            set_cmd=self._set_max_position,
            get_cmd=self._get_max_position,
            vals=vals.Numbers(0, 360),
            instrument=self
        )

        self.min_position = Parameter(
            'min_position',
            label='Minimum position',
            set_cmd=self._set_min_position,
            get_cmd=self._get_min_position,
            vals=vals.Numbers(0, 360),
            instrument=self
        )

        self.velocity = Parameter(
            'velocity',
            label='Move velocity',
            unit='\u00b0/s',
            set_cmd=self._set_move_velocity,
            get_cmd=self._get_move_velocity,
            vals=vals.Numbers(0, 25),
            instrument=self
        )

        self.jog_velocity = Parameter(
            'jog_velocity',
            label='Jog velocity',
            unit='\u00b0/s',
            set_cmd=self._set_jog_velocity,
            get_cmd=self._get_jog_velocity,
            vals=vals.Numbers(0, 25),
            instrument=self
        )

        self.homing_velocity = Parameter(
            'homing_velocity',
            label='Homing velocity',
            unit='\u00b0/s',
            set_cmd=self._set_homing_velocity,
            get_cmd=self._get_homing_velocity,
            vals=vals.Numbers(0.1, 25),
            instrument=self
        )

        self.acceleration = Parameter(
            'acceleration',
            label='Move acceleration',
            unit='\u00b0/s\u00b2',
            set_cmd=self._set_move_acceleration,
            get_cmd=self._get_move_acceleration,
            vals=vals.Numbers(0, 25),
            instrument=self
        )

        self.jog_acceleration = Parameter(
            'jog_acceleration',
            label='Jog acceleration',
            unit='\u00b0/s\u00b2',
            set_cmd=self._set_jog_acceleration,
            get_cmd=self._get_jog_acceleration,
            vals=vals.Numbers(0, 25),
            instrument=self
        )

        self.jog_mode = Parameter(
            'jog_mode',
            set_cmd=self._set_jog_mode,
            get_cmd=self._get_jog_mode,
            vals=vals.Enum('continuous', 'stepped'),
            instrument=self
        )

        self.jog_step_size = Parameter(
            'jog_step_size',
            set_cmd=self._set_jog_step_size,
            get_cmd=self._get_jog_step_size,
            vals=vals.Numbers(0.0005, 360),
            instrument=self
        )

        self.stop_mode = Parameter(
            'stop_mode',
            set_cmd=self._set_stop_mode,
            get_cmd=self._get_stop_mode,
            vals=vals.Enum('immediate', 'profiled'),
            instrument=self
        )

        self.soft_limits_mode = Parameter(
            'soft_limits_mode',
            set_cmd=self._set_soft_limits_mode,
            get_cmd=self._get_soft_limits_mode,
            vals=vals.Enum('disallow', 'partial', 'all'),
            instrument=self
        )

        self.backlash = Parameter(
            'backlash',
            unit='\u00b0',
            set_cmd=self._set_backlash,
            get_cmd=self._get_backlash,
            vals=vals.Numbers(0, 5),
            instrument=self
        )

        self.connect_message()

    def identify(self) -> None:
        """Sends a command to the device to make it identify itself"""
        self._dll.CC_Identify(self._serial_number)

    def get_idn(self) -> dict:
        """Get device identifier"""
        idparts = ['Thorlabs', self.model, self.version, self.serial_number]
        return dict(zip(('vendor', 'model', 'serial', 'firmware'), idparts))

    def go_home(self, block=True):
        """Home the device: set the device to a known state and home position

        Args:
            block (bool, optional): will wait for completion. Defaults to True.
        """
        self._check_error(self._dll.CC_Home(self._serial_number))
        self.homed = True
        if block:
            self.wait_for_completion()

    def enable_simulation(self) -> None:
        """Initialise a connection to the simulation manager, which must already be running"""
        self._dll.TLI_InitializeSimulations()

    def disable_simulation(self) -> None:
        """Uninitialize a connection to the simulation manager, which must be running"""
        self._dll.TLI_UninitializeSimulations()

    def wait_for_completion(self, status: str = 'homed', max_time = 5) -> None:
        """Wait for the current function to be finished.

        Args:
            status (str, optional): expected status. Defaults to 'homed'.
            max_time (int, optional): maximum waiting time for the internal loop. Defaults to 5.
        """
        message_type = ctypes.c_ushort()
        message_id = ctypes.c_ushort()
        message_data = ctypes.c_ulong()
        cond = self._CONDITIONS.index(status)

        if status == 'stopped':
            if not self.is_moving():
                return None
        elif status == 'homed':
            max_time = 0

        while self._dll.CC_MessageQueueSize(self._serial_number) <= 0:
            sleep(.2)

        self._dll.CC_WaitForMessage(
            self._serial_number, ctypes.byref(message_type),
            ctypes.byref(message_id), ctypes.byref(message_data)
        )

        start = time()
        while int(message_type.value) != 2 or int(message_id.value) != cond:
            end = time()
            if end - start > max_time and max_time != 0:
                raise RuntimeError(f'waited for {max_time} for {status} to complete'
                                   f'message type: {message_type.value} ({message_id.value})')

            if self._dll.CC_MessageQueueSize(self._serial_number) <= 0:
                sleep(.2)
                continue
            self._dll.CC_WaitForMessage(
                self._serial_number,
                ctypes.byref(message_type),
                ctypes.byref(message_id),
                ctypes.byref(message_data)
            )
        return None

    def _device_unit_to_real(self, device_unit: int, unit_type: int) -> float:
        """Converts a device unit to a real world unit

        Args:
            device_unit (int): the device unit.
            unit_type (int): the type of unit. Distance: 0, velocity: 1, acceleration: 2.

        Returns:
            float: real unit value
        """
        real_unit = ctypes.c_double()
        ret = self._dll.CC_GetRealValueFromDeviceUnit(
            self._serial_number, ctypes.c_int(device_unit),
            ctypes.byref(real_unit), ctypes.c_int(unit_type)
        )
        self._check_error(ret)
        return real_unit.value

    def _real_to_device_unit(self, real_unit: float, unit_type: int) -> int:
        """Converts a real world unit to a device unit

        Args:
            real_unit (float): the real unit
            unit_type (int): the type of unit. Distance: 0, velocity: 1, acceleration: 2

        Returns:
            int: device unit
        """
        device_unit = ctypes.c_int()
        ret = self._dll.CC_GetDeviceUnitFromRealValue(
            self._serial_number, ctypes.c_double(real_unit),
            ctypes.byref(device_unit), ctypes.c_int(unit_type)
        )
        self._check_error(ret)
        return device_unit.value

    def _get_backlash(self) -> float:
        """Get the backlash distance setting (used to control hysteresis)"""
        ret = self._dll.CC_GetBacklash(self._serial_number)
        return self._device_unit_to_real(ret, 0)

    def _set_backlash(self, value: float) -> None:
        """Set the backlash distance setting (used to control hysteresis)"""
        val = self._real_to_device_unit(value, 0)
        ret = self._dll.CC_SetBacklash(self._serial_number, ctypes.c_long(val))
        self._check_error(ret)

    def _get_homing_velocity(self) -> float:
        vel = self._dll.CC_GetHomingVelocity(self._serial_number)
        return self._device_unit_to_real(vel, 1)

    def _set_homing_velocity(self, velocity: float) -> None:
        vel = self._real_to_device_unit(velocity, 1)
        ret = self._dll.CC_SetHomingVelocity(self._serial_number,
                                             ctypes.c_uint(vel))
        self._check_error(ret)

    def _get_jog_mode(self) -> str:
        jog_mode = ctypes.c_short()
        stop_mode = ctypes.c_short()
        ret = self._dll.CC_GetJogMode(self._serial_number,
                                      ctypes.byref(jog_mode),
                                      ctypes.byref(stop_mode))
        self._check_error(ret)
        if jog_mode.value == ctypes.c_short(0x01).value:
            return 'continuous'
        elif jog_mode.value == ctypes.c_short(0x02).value:
            return 'stepped'
        else:
            raise RuntimeError('Unexpected value received from Kinesis')

    def _set_jog_mode(self, mode: str) -> None:
        jog_mode = ctypes.c_short(0x00)
        stop_mode = ctypes.c_short(0x00)
        stop_mode = self._get_stop_mode()

        if mode == 'continuous':
            jog_mode = ctypes.c_short(0x01)
        elif mode == 'stepped':
            jog_mode = ctypes.c_short(0x02)
        if stop_mode == 'immediate':
            stop_mode = ctypes.c_short(0x01)
        elif stop_mode == 'profiled':
            stop_mode = ctypes.c_short(0x02)

        ret = self._dll.CC_SetJogMode(self._serial_number,
                                      jog_mode, stop_mode)
        self._check_error(ret)
        return None

    def _get_jog_step_size(self) -> float:
        ret = self._dll.CC_GetJogStepSize(self._serial_number)
        return self._device_unit_to_real(ret, 0)

    def _set_jog_step_size(self, step_size: float) -> None:
        step = self._real_to_device_unit(step_size, 0)
        ret = self._dll.CC_SetJogStepSize(self._serial_number,
                                          ctypes.c_uint(step))
        self._check_error(ret)
        return None

    def _check_connection(self) -> bool:
        ret = self._dll.CC_CheckConnection(self._serial_number)
        return bool(ret)

    def _get_stop_mode(self):
        jog_mode = ctypes.c_short()
        stop_mode = ctypes.c_short()
        ret = self._dll.CC_GetJogMode(self._serial_number,
                                      ctypes.byref(jog_mode),
                                      ctypes.byref(stop_mode))
        self._check_error(ret)
        if stop_mode.value == ctypes.c_short(0x01).value:
            return 'immediate'
        elif stop_mode.value == ctypes.c_short(0x02).value:
            return 'profiled'
        else:
            raise RuntimeError('unexpected value received from Kinesis')

    def _set_stop_mode(self, mode: str) -> None:
        jog_mode = ctypes.c_short(0x00)
        stop_mode = ctypes.c_short(0x00)

        jmode = self._get_jog_mode()
        if jmode == 'continuous':
            jog_mode = ctypes.c_short(0x01)
        elif jmode == 'stepped':
            jog_mode = ctypes.c_short(0x02)
        if mode == 'immediate':
            stop_mode = ctypes.c_short(0x01)
        elif mode == 'profiled':
            stop_mode = ctypes.c_short(0x02)

        ret = self._dll.CC_SetJogMode(self._serial_number,
                                      jog_mode, stop_mode)
        self._check_error(ret)
        return None

    def _get_max_position(self) -> float:
        max_pos = ctypes.c_int()
        self._dll.CC_GetStageAxisMaxPos(self._serial_number, max_pos)
        return self._device_unit_to_real(max_pos.value, 0)

    def _set_max_position(self, max_val: float) -> None:
        min_val = self._get_min_position()
        min_val = self._real_to_device_unit(min_val, 0)
        max_val = self._real_to_device_unit(max_val, 0)
        ret = self._dll.CC_SetStageAxisLimits(self._serial_number,
                                              ctypes.c_int(min_val),
                                              ctypes.c_int(max_val))
        self._check_error(ret)
        self.wait_for_completion('limit_updated')

    def _get_min_position(self) -> float:
        min_pos = ctypes.c_int()
        self._dll.CC_GetStageAxisMinPos(self._serial_number, min_pos)
        return self._device_unit_to_real(min_pos.value, 0)

    def _set_min_position(self, min_val: float) -> None:
        max_val = self._get_max_position()
        max_val = self._real_to_device_unit(max_val, 0)
        min_val = self._real_to_device_unit(min_val, 0)
        ret = self._dll.CC_SetStageAxisLimits(self._serial_number,
                                              ctypes.c_int(min_val),
                                              ctypes.c_int(max_val))
        self._check_error(ret)
        self.wait_for_completion('limit_updated')

    def _get_soft_limits_mode(self) -> str:
        """Gets the software limits mode."""
        mode = ctypes.c_int16()
        self._dll.CC_GetSoftLimitMode(self._serial_number, ctypes.byref(mode))
        if mode.value == ctypes.c_int16(0).value:
            return 'disallow'
        elif mode.value == ctypes.c_int16(1).value:
            return 'partial'
        elif mode.value == ctypes.c_int16(2).value:
            return 'all'
        else:
            raise RuntimeError('unexpected value received from Kinesis')

    def _set_soft_limits_mode(self, mode: str) -> None:
        """Sets the software limits mode"""
        if mode == 'disallow':
            lmode = ctypes.c_int16(0)
        elif mode == 'partial':
            lmode = ctypes.c_int16(1)
        elif mode == 'all':
            lmode = ctypes.c_int16(2)

        ret = self._dll.CC_SetLimitsSoftwareApproachPolicy(self._serial_number,
                                                           lmode)
        self._check_error(ret)

    def _get_move_velocity(self) -> float:
        acceleration = ctypes.c_int()
        velocity = ctypes.c_int()
        ret = self._dll.CC_GetVelParams(self._serial_number,
                                        ctypes.byref(acceleration),
                                        ctypes.byref(velocity))
        self._check_error(ret)
        return self._device_unit_to_real(velocity.value, 1)

    def _set_move_velocity(self, velocity: float) -> None:
        vel = self._real_to_device_unit(velocity, 1)
        accel = self._real_to_device_unit(self._get_move_acceleration(), 2)
        ret = self._dll.CC_SetVelParams(self._serial_number,
                                        ctypes.c_int(accel),
                                        ctypes.c_int(vel))
        self._check_error(ret)

    def _get_move_acceleration(self) -> float:
        acceleration = ctypes.c_int()
        velocity = ctypes.c_int()
        ret = self._dll.CC_GetVelParams(self._serial_number,
                                        ctypes.byref(acceleration),
                                        ctypes.byref(velocity))
        self._check_error(ret)
        return self._device_unit_to_real(acceleration.value, 2)

    def _set_move_acceleration(self, acceleration: float) -> None:
        vel = self._real_to_device_unit(self._get_move_velocity(), 1)
        accel = self._real_to_device_unit(acceleration, 2)
        ret = self._dll.CC_SetVelParams(self._serial_number,
                                        ctypes.c_int(accel),
                                        ctypes.c_int(vel))
        self._check_error(ret)

    def _get_jog_velocity(self) -> float:
        acceleration = ctypes.c_int()
        velocity = ctypes.c_int()
        ret = self._dll.CC_GetJogVelParams(self._serial_number,
                                           ctypes.byref(acceleration),
                                           ctypes.byref(velocity))
        self._check_error(ret)
        return self._device_unit_to_real(velocity.value, 1)

    def _set_jog_velocity(self, velocity: float) -> None:
        vel = self._real_to_device_unit(velocity, 1)
        accel = self._real_to_device_unit(self._get_jog_acceleration(), 2)
        ret = self._dll.CC_SetJogVelParams(self._serial_number,
                                           ctypes.c_int(accel),
                                           ctypes.c_int(vel))
        self._check_error(ret)

    def _get_jog_acceleration(self) -> float:
        acceleration = ctypes.c_int()
        velocity = ctypes.c_int()
        ret = self._dll.CC_GetJogVelParams(self._serial_number,
                                           ctypes.byref(acceleration),
                                           ctypes.byref(velocity))
        self._check_error(ret)
        return self._device_unit_to_real(acceleration.value, 2)

    def _set_jog_acceleration(self, acceleration: float) -> None:
        vel = self._real_to_device_unit(self._get_jog_velocity(), 1)
        accel = self._real_to_device_unit(acceleration, 2)
        ret = self._dll.CC_SetJogVelParams(self._serial_number,
                                           ctypes.c_int(accel),
                                           ctypes.c_int(vel))
        self._check_error(ret)

    def _get_position(self) -> float:
        pos = self._dll.CC_GetPosition(self._serial_number)
        return self._device_unit_to_real(pos, 0)

    def _set_position(self, position: float, block: bool=True) -> None:
        pos = self._real_to_device_unit(position, 0)
        ret = self._dll.CC_SetMoveAbsolutePosition(self._serial_number,
                                                   ctypes.c_int(pos))
        self._check_error(ret)
        ret = self._dll.CC_MoveAbsolute(self._serial_number)
        self._check_error(ret)
        if block:
            while (self._get_position() - position) < .001:
                sleep(.2) 
        
    def is_moving(self) -> bool:
        """check if the motor cotnroller is moving."""
        status_bit = ctypes.c_short()
        self._dll.CC_GetStatusBits(self._serial_number,
                                   ctypes.byref(status_bit))
        if status_bit.value & 0x10 or status_bit.value & 0x20:
            return True
        else:
            return False

    def move_to(self, position: float, block=True) -> None:
        """Move the device to the specified position.
        The motor may need to be homed before a position can be set.

        Args:
            position (float): the set position
            block (bool, optional): will wait until complete. Defaults to True.
        """
        pos = self._real_to_device_unit(position, 0)
        ret = self._dll.CC_MoveToPosition(self._serial_number,
                                          ctypes.c_int(pos))
        self._check_error(ret)

        if block:
            self.wait_for_completion(status='moved', max_time=15)
        self.position.get()

    def move_by(self, displacement: float, block: bool = True) -> None:
        """Move the motor by a relative amount

        Args:
            displacement (float): amount to move
            block (bool, optional): will wait until complete. Defaults to True.
        """
        dis = self._real_to_device_unit(displacement, 0)
        ret = self._dll.CC_MoveRelative(self._serial_number,
                                        ctypes.c_int(dis))
        self._check_error(ret)
        if block:
            self.wait_for_completion(status='moved')
        self.position.get()

    def move_continuous(self, direction: str = 'forward') -> None:
        """start moving at the current velocity in the specified direction

        Args:
            direction (str, optional): the required direction of travel.
                Defaults to 'forward'. Accepts 'forward' or 'reverse'
        """
        if direction == 'forward' or direction == 'forwards':
            direc = ctypes.c_short(0x01)
        elif direction == 'reverse' or direction == 'backward' or direction == 'backwards':
            direc = ctypes.c_short(0x02)
        else:
            raise ValueError('direction unrecognised')

        ret = self._dll.CC_MoveAtVelocity(self._serial_number, direc)
        self._check_error(ret)
        self.position.get()

    def jog(self, direction: str = 'forward', block: bool = True) -> None:
        """Performs a jog

        Args:
            direction (str): the jog direction. Defaults to 'forward'.
                Accepts 'forward' or 'reverse'
            block (bool, optional): will wait until complete. Defaults to True.
        """
        if direction == 'forward' or direction == 'forwards':
            direc = ctypes.c_short(0x01)
        elif direction == 'reverse' or direction == 'backward' or direction == 'backwards':
            direc = ctypes.c_short(0x02)
        else:
            raise ValueError('direction unrecognised')

        ret = self._dll.CC_MoveJog(self._serial_number, direc)
        self._check_error(ret)
        if self._get_jog_mode() =='stepped':
            if block:
                self.wait_for_completion(status='moved')
        self.position.get()

    def stop(self, immediate: bool = False) -> None:
        """Stop the current move

        Args:
            immediate (bool, optional):
                True: stops immediately (with risk of losing track of position).
                False: stops using the current velocity profile.
                Defaults to False.
        """
        if immediate:
            ret = self._dll.CC_StopImmediate(self._serial_number)
        else:
            ret = self._dll.CC_StopProfiled(self._serial_number)
        self._check_error(ret)
        self.wait_for_completion(status='stopped')
        self.position.get()

    def close(self):
        if self._simulation:
            self.disable_simulation()
        if hasattr(self, '_serial_number'):
            self._dll.CC_Close(self._serial_number)

    def _get_hardware_info(self) -> list:
        """Gets the hardware information from the device

        Returns:
            list: [model number, hardware type number, number of channels,
                notes describing the device, firmware version, hardware version,
                hardware modification state]
        """
        model = ctypes.create_string_buffer(8)
        model_size = ctypes.c_ulong(8)
        type_num = ctypes.c_ushort()
        channel_num = ctypes.c_ushort()
        notes = ctypes.create_string_buffer(48)
        notes_size = ctypes.c_ulong(48)
        firmware_version = ctypes.c_ulong()
        hardware_version = ctypes.c_ushort()
        modification_state = ctypes.c_ushort()

        ret = self._dll.CC_GetHardwareInfo(
            self._serial_number,
            ctypes.byref(model), model_size,
            ctypes.byref(type_num), ctypes.byref(channel_num),
            ctypes.byref(notes), notes_size, ctypes.byref(firmware_version),
            ctypes.byref(hardware_version), ctypes.byref(modification_state)
        )

        self._check_error(ret)
        return [model.value, type_num.value, channel_num.value,
                notes.value, firmware_version.value, hardware_version.value,
                modification_state.value]

    def _get_device_info(self) -> list:
        """Get the device information from the USB port

        Returns:
            list: [type id, description, PID, is known type, motor type,
            is piezo, is laser, is custom type, is rack, max channels]
        """
        type_id = ctypes.c_ulong()
        description = ctypes.c_char()
        pid = ctypes.c_ulong()
        is_known_type = ctypes.c_bool()
        motor_type = ctypes.c_int()
        is_piezo_device = ctypes.c_bool()
        is_laser = ctypes.c_bool()
        is_custom_type = ctypes.c_bool()
        is_rack = ctypes.c_bool()
        max_channels = ctypes.c_bool()

        ret = self._dll.TLI_GetDeviceInfo(
            ctypes.byref(self._serial_number),
            ctypes.byref(type_id),
            ctypes.byref(description),
            ctypes.byref(pid),
            ctypes.byref(is_known_type),
            ctypes.byref(motor_type),
            ctypes.byref(is_piezo_device),
            ctypes.byref(is_laser),
            ctypes.byref(is_custom_type),
            ctypes.byref(is_rack),
            ctypes.byref(max_channels)
        )
        self._check_error(ret)
        return [type_id.value, description.value, pid.value,
                is_known_type.value, motor_type.value, is_piezo_device.value,
                is_laser.value, is_custom_type.value, is_rack.value,
                max_channels.value]

    def _load_settings(self):
        """Update device with stored settings"""
        self._dll.CC_LoadSettings(self._serial_number)
        return None

    def _set_limits_approach(self, limit: int):
        disallow_illegal_moves = ctypes.c_int16(0)
        allow_partial_moves = ctypes.c_int16(1)
        allow_all_moves = ctypes.c_int16(2)
        limits_approach_policy = ctypes.c_int16(limit)

        self._dll.CC_SetLimitsSoftwareApproachPolicy(
            self._serial_number, ctypes.byref(disallow_illegal_moves),
            ctypes.byref(allow_partial_moves), ctypes.byref(allow_all_moves),
            ctypes.byref(limits_approach_policy)
        )
        return None

    def _start_polling(self, polling: int):
        pol = ctypes.c_int(polling)
        self._dll.CC_StartPolling(self._serial_number, ctypes.byref(pol))
        return None

    def _clear_message_queue(self) -> None:
        self._dll.CC_ClearMessageQueue(self._serial_number)
        return None

    def _can_home(self) -> bool:
        ret = self._dll.CC_CanHome(self._serial_number)
        return bool(ret)

    def _check_error(self, status: int) -> None:
        if status != 0:
            if status in ConnexionErrors:
                raise ConnectionError(f'{ConnexionErrors[status]} ({status})')
            elif status in GeneralErrors:
                raise OSError(f'{GeneralErrors[status]} ({status})')
            elif status in MotorErrors:
                raise RuntimeError(f'{MotorErrors[status]} ({status})')
            else:
                raise ValueError(f'Unknown error code ({status})')
        else:
            pass
        return None
