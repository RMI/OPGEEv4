from ..log import getLogger
from ..process import Process
from ..stream import PHASE_LIQUID
from opgee import ureg
from ..compressor import Compressor
from ..energy import Energy, EN_NATURAL_GAS, EN_ELECTRICITY, EN_DIESEL
from ..emissions import Emissions, EM_COMBUSTION, EM_LAND_USE, EM_VENTING, EM_FLARING, EM_FUGITIVES


_logger = getLogger(__name__)


class GasReinjectionCompressor(Process):
    def _after_init(self):
        super()._after_init()
        self.field = field = self.get_field()
        self.gas = field.gas
        self.std_temp = field.model.const("std-temperature")
        self.std_press = field.model.const("std-pressure")
        self.res_press = field.attr("res_press")
        self.prime_mover_type = self.attr("prime_mover_type")
        self.eta_compressor = field.attr("eta_compressor")

    def run(self, analysis):
        self.print_running_msg()

        input = self.find_input_stream("gas for gas reinjection compressor")
        temp = input.temperature
        press = input.pressure

        if input.total_flow_rate().m == 0 or not self.enabled:
            return

        loss_rate = self.venting_fugitive_rate()
        gas_fugitives_temp = self.set_gas_fugitives(input, loss_rate)
        gas_fugitives = self.find_output_stream("gas fugitives")
        gas_fugitives.copy_flow_rates_from(gas_fugitives_temp)
        gas_fugitives.set_temperature_and_pressure(self.std_temp, self.std_press)

        discharge_press = self.res_press + ureg.Quantity(500, "psi")
        overall_compression_ratio = discharge_press / press
        compression_ratio = Compressor.get_compression_ratio(overall_compression_ratio)
        num_stages = Compressor.get_num_of_compression(overall_compression_ratio)
        total_work, _ = Compressor.get_compressor_work_temp(self.field, temp, press, input, compression_ratio,
                                                            num_stages)
        volume_flow_rate_STP = self.gas.tot_volume_flow_rate_STP(input)
        total_energy = total_work * volume_flow_rate_STP
        brake_horse_power = total_energy / self.eta_compressor
        energy_consumption = self.get_energy_consumption(self.prime_mover_type, brake_horse_power)

        gas_to_well = self.find_output_stream("gas for gas reinjection well")
        gas_to_well.copy_flow_rates_from(input)
        gas_to_well.subtract_gas_rates_from(gas_fugitives)

        incoming_gas_consumed = energy_consumption / self.gas.energy_flow_rate(input)
        gas_to_well.multiply_flow_rates(1-incoming_gas_consumed.m)

        # energy-use
        energy_use = self.energy
        if self.prime_mover_type == "NG_engine" or "NG_turbine":
            energy_carrier = EN_NATURAL_GAS
        elif self.prime_mover_type == "Electric_motor":
            energy_carrier = EN_ELECTRICITY
        else:
            energy_carrier = EN_DIESEL
        energy_use.set_rate(energy_carrier, energy_consumption)

        # emissions
        emissions = self.emissions
        energy_for_combustion = energy_use.data.drop("Electricity")
        combustion_emission = (energy_for_combustion * self.process_EF).sum()
        emissions.add_rate(EM_COMBUSTION, "CO2", combustion_emission)

        emissions.add_from_stream(EM_FUGITIVES, gas_fugitives)
