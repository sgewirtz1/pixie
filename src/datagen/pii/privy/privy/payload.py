# Copyright 2018- The Pixie Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0
import os
import time
import pathlib
import warnings
import logging
import random
from datetime import timedelta
from copy import deepcopy
import traceback
import schemathesis
from joblib import Parallel, delayed
from tqdm_joblib import tqdm_joblib
from tqdm import tqdm
from alive_progress import alive_bar
from schemathesis import DataGenerationMethod
from hypothesis import (
    HealthCheck,
    given,
    Verbosity,
    settings,
    strategies as st,
)
from privy.hooks import SchemaHooks, ParamType
from privy.route import PayloadRoute
from privy.analyze import DatasetAnalyzer
# todo @benkilimnik add fine grained warning filter for schemathesis
warnings.filterwarnings("ignore")


class PayloadGenerator:

    def __init__(self, api_specs_folder, file_writers, args):
        self.args = args
        self.api_specs_folder = api_specs_folder
        self.log = logging.getLogger("privy")
        self.analyzer = DatasetAnalyzer(args.region)
        self.route = PayloadRoute(file_writers, self.analyzer, args)
        self.hook = SchemaHooks(args).schema_analyzer
        self.providers = args.region
        self.api_specs = []
        self.http_types = ["get", "head", "post", "put",
                           "delete", "connect", "options", "trace", "patch"]

    def generate_payloads(self):
        """Generate synthetic API request payloads from openAPI specs."""
        num_files = sum(len(files) for _, _, files in os.walk(self.api_specs_folder))
        self.log.info(
            f"Generating synthetic request payloads from {num_files} files in {self.api_specs_folder}")
        # Retrieve openapi descriptor files
        for dirpath, _, files in os.walk(self.api_specs_folder):
            descriptors = filter(lambda f: f in [
                                 "openapi.json", "swagger.json", "openapi.yaml", "swagger.yaml"], files)
            for desc in descriptors:
                file = pathlib.Path(dirpath) / desc
                self.api_specs.append(file)
        # multi-threaded
        if self.args.multi_threaded:
            with tqdm_joblib(tqdm(total=num_files, position=0, leave=True)) as progress_bar:
                Parallel(n_jobs=10, prefer='threads')(
                    delayed(self.parse_openapi_descriptor)(file, self.args.timeout) for file in self.api_specs
                )
                progress_bar.update()
        # single-threaded
        else:
            with alive_bar(num_files) as progress_bar:
                for file in self.api_specs:
                    self.parse_openapi_descriptor(file, self.args.timeout)
                    progress_bar()

    def parse_openapi_descriptor(self, file, timeout):
        self.log.info(f"Generating {file}...")
        start = time.time()
        try:
            schema = schemathesis.from_path(
                file, data_generation_methods=[DataGenerationMethod.positive]
            )
            self.parse_http_methods(schema=schema, start=time.time(), timeout=timeout)
            self.analyzer.print_metrics()
            self.analyzer.reset_spec_specific_metrics()
            end = time.time()
            self.log.info(f"Success in {round(end - start, 2)} seconds")
        except Exception:
            end = time.time()
            self.log.warning(f"Failed to generate {file}")
            self.log.warning(f"Failed after {round(end - start, 2)} seconds")
            self.analyzer.print_metrics()
            self.analyzer.reset_spec_specific_metrics()
            self.log.warning(traceback.format_exc())

    def fuzz_label(self, label) -> str:
        """Alter an input label, inserting a random delimiter."""
        return label.replace(" ", random.choice(["-", "_", "__", ".", ":", "", " "]))

    def insert_pii(self, pii, case_attr, parameter_type):
        """Assign a pii value to a parameter for the input case attribute (e.g. case.path_parameters)."""
        self.log.debug(f"|Inserting additional pii type| {pii.label} |with category| {pii.category}")
        if self.args.fuzz_payloads:
            fuzzed_label = self.fuzz_label(pii.label)
            case_attr[fuzzed_label] = pii.value
        case_attr[pii.label] = pii.value
        self.hook.add_pii_type(parameter_type, pii.label, pii.category)

    def generate_pii_case(self, case_attr, parameter_type):
        """insert additional pii data into a request payload or generate new payload"""
        """insert additional PII data into a request payload or generate new PII payload"""
        if self.args.equalize_pii_distribution_to_percentage:
            self.log.debug("Inserting additional random PII to equalize distribution of PII types")
            if random.randint(0, 1):
                # sample just one pii label (with the lowest count) 50% of the time
                min_pii_type, count = self.analyzer.get_lowest_count_pii_type()
                self.log.debug(f"Inserting PII type |{min_pii_type}| with count |{count}|")
                pii = self.providers.get_pii(min_pii_type)
                self.insert_pii(pii, case_attr, parameter_type)
            else:
                # choose between 1-{num_additional_pii_types} pii types with the lowest count
                num_pii_types = random.randint(1, self.args.num_additional_pii_types)
                for pii_type, count in self.analyzer.k_lowest_pii_types(num_pii_types):
                    self.log.debug(f"Inserting PII type: |{pii_type}| with count |{count}|")
                    pii = self.providers.get_pii(pii_type)
                    self.insert_pii(pii, case_attr, parameter_type)
        # randomize order of parameters
        case_attr = list(case_attr.items())
        random.shuffle(case_attr)
        case_attr = dict(case_attr)
        return case_attr

    @settings(
        verbosity=Verbosity.quiet,
        deadline=timedelta(milliseconds=5000),
        max_examples=1,
        suppress_health_check=(HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much),
    )
    @given(data=st.data())
    def parse_http_methods(self, data, schema, start, timeout):
        """instantiate synthetic request payload and choose data providers for a given openapi spec"""
        for path in schema.keys():
            for http_type in self.http_types:
                method = schema[path].get(http_type, None)
                if method:
                    break
            # choose default strategies (data generators in hypothesis) based on schema of api path
            strategy = method.as_strategy()
            # replace default strategies with custom providers in providers.py using before_generate_case in hooks.py
            # and generate data for path parameters in this api spec
            case = data.draw(strategy)
            # write generated request parameters to csv
            self.route.write_payload_to_csv(
                case.path_parameters, self.hook.has_pii(ParamType.PATH), self.hook.get_pii_types(ParamType.PATH)
            )
            self.route.write_payload_to_csv(
                case.query, self.hook.has_pii(ParamType.QUERY), self.hook.get_pii_types(ParamType.QUERY)
            )
            # ------ EQUALIZE PII DISTRIBUTION ------
            # often in pii requests, the parameters are not given pii keywords for security reasons
            # to account for this we insert additional random pii fields in requests we know contain pii
            # until {equalize_to_percentage}% of payloads contain PII
            while round(self.analyzer.percent_pii) < self.args.equalize_pii_distribution_to_percentage:
                self.log.debug(f"Equalizing PII distribution because {round(self.analyzer.percent_pii)}% is not 50%")
                original_path_pii_types = self.hook.deepcopy_pii_types(ParamType.PATH)
                original_query_pii_types = self.hook.deepcopy_pii_types(ParamType.QUERY)
                if not case.path_parameters and not case.query:
                    break
                if case.path_parameters:
                    pii_path_params = self.generate_pii_case(deepcopy(case.path_parameters), ParamType.PATH)
                    self.route.write_payload_to_csv(
                        pii_path_params, self.hook.has_pii(ParamType.PATH), self.hook.get_pii_types(ParamType.PATH)
                    )
                    self.hook.overwrite_pii_types(ParamType.PATH, original_path_pii_types)
                if case.query:
                    pii_path_params = self.generate_pii_case(deepcopy(case.query), ParamType.QUERY)
                    self.route.write_payload_to_csv(
                        pii_path_params, self.hook.has_pii(ParamType.QUERY), self.hook.get_pii_types(ParamType.QUERY)
                    )
                    self.hook.overwrite_pii_types(ParamType.QUERY, original_query_pii_types)
            self.hook.clear_pii_types(ParamType.PATH)
            self.hook.clear_pii_types(ParamType.QUERY)

            if time.time() - start > timeout:
                self.log.warning(f"OpenAPI spec took too long to parse. Timeout of {timeout} reached.")
                return
