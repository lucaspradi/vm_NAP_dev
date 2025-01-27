#Library imports
import argparse
import io
import logging
import os
import sys
from datetime import datetime
import pandas as pd
from IPython.display import display, Markdown
import re
import subprocess

#Get the absolute path of the root directory (one level up from 'src')
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)

#Local application/library specific imports
from prepare_virtual_metabolization import *
from run_virtual_metabolization import *

class StreamToLogger:
    """
    Redirect writes to a logger instance. This is particularly useful for
    redirecting stdout from third-party libraries that use print statements.
    """
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        pass

class SuppressOutput:
    """
    Temporarily redirect stdout to prevent print statements from executing.
    Useful in scenarios where you want to suppress noise from third-party libraries.
    """
    def __enter__(self):
        self._original_stdout = sys.stdout
        sys.stdout = io.StringIO()

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self._original_stdout

class CaptureOutput:
    """
    Context manager to capture and filter the standard output.
    """
    def __enter__(self):
        self._original_stdout = sys.stdout
        self._captured_stdout = io.StringIO()
        sys.stdout = self._captured_stdout
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self._original_stdout

    def get_filtered_output(self):
        output = self._captured_stdout.getvalue()
        filtered_output = '\n'.join(line for line in output.splitlines()
                                    if not line.startswith("Applying") and not line.startswith("Cycle"))
        return filtered_output

#Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    filename='vm_nap_log.txt', filemode='w')
logging.getLogger('sygma').setLevel(logging.WARNING)  #Adjust the logger name if different
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

#Redirect stdout to logger
sys.stdout = StreamToLogger(logging.getLogger('STDOUT'), logging.INFO)

def package_version(package_name):
    """
    Get the version of a Python package using pip, subprocess, and regular expressions.
    """
    
    result = subprocess.run(['pip', 'show', package_name], stdout=subprocess.PIPE, text=True)

    # Decode the result to a string (if using Python < 3.7, use result.stdout.decode())
    output = result.stdout

    # Use a regular expression to find the version number in the output
    version_match = re.search(r'Version: (.+)', output)
    if version_match:
        version = version_match.group(1)
        return version
    else:
        print(f"Version not found for the package {package_name}")

def main(args):
    """
    Main function to execute the vm_NAP processing workflow.
    """
    print( '')
    print( '##STARTING vm-NAP version 1.0.0')
    print( '')
    logging.info("Script started with arguments: %s", args)
    print( '')
    print( '##GNPS_POSTPROCESSING Package version: '+package_version("gnps_postprocessing"))
    print( '')

    #Constructing the dynamic string based on provided arguments
    dynamic_string = args.job_id if args.job_id.lower() != 'false' else 'no_job_id'

    if args.sirius_input_file:
        dynamic_string += "_" + os.path.splitext(os.path.basename(args.sirius_input_file))[0]

    if args.extra_compounds_table_file:
        dynamic_string += "_" + os.path.splitext(os.path.basename(args.extra_compounds_table_file))[0]

    if args.compound_name_to_keep:
        dynamic_string += "_filtered_by_names"

    #Adding a timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dynamic_string += "_" + timestamp

    #Use dynamic_string in your script where needed
    #For example, in file naming or logging
    #print(f"Dynamic string: {dynamic_string}")

    prepare_for_virtual_metabolization.list_compound_name = []
    prepare_for_virtual_metabolization.list_smiles = []
    job_id = args.job_id

    print( '###MOLECULAR NETWORKING ')
    if args.job_id.lower() !='false':
        job_id = args.job_id
        gnps_download_results(job_id, output_folder=job_id)

        gnps_download_results_df_annotations_filtered = gnps_filter_annotations(
            gnps_download_results.df_annotations, 'INCHI', 
            args.ionisation_mode, args.max_ppm_error, args.min_cosine, 
            args.shared_peaks, args.max_spec_charge, prefix='')

        df_annotations_consolidated  = consolidate_and_convert_structures(gnps_download_results_df_annotations_filtered, prefix='', 
                                                                    smiles='Smiles', inchi='INCHI')
        print( '')
        df_annotations = get_info_gnps_annotations(df_annotations_consolidated, 
                                                inchi_column='Consol_InChI', 
                                                smiles_column='Consol_SMILES', 
                                                smiles_planar_column='Consol_SMILES_iso')

        #Optional filtering based on compound names
        df_annotations_filtered = apply_filtering(df_annotations, args.compound_name_to_keep)
        #print('Number of annotations after filtering = ' + str(df_annotations_filtered.shape[0]))
        print( '')

        prepare_for_virtual_metabolization(df_annotations_filtered,
                                        compound_name='Compound_Name',
                                        smiles_column='Consol_SMILES', 
                                        smiles_planar_column='Consol_SMILES_iso',
                                        drop_duplicated_structure=True, 
                                        use_planar_structure=args.use_planar_structure_boolean)

        print( '')

    else:
        print("Skipping GNPS download and processing as job_id is set to 'False'.")

    print( '###SIRIUS (OPTIONAL)')
    if args.sirius_input_file:
    #Check if the file exists
        if not os.path.exists(args.sirius_input_file):
            print(f"File not found: {args.sirius_input_file}")
        else:
            print("Loading SIRIUS input data...")
            df_sirius = load_csifingerid_cosmic_annotations(args.sirius_input_file)

            #Apply filtering based on scores and database links
            df_score_filtered = df_csifingerid_cosmic_annotations_filtering(df_sirius, args.zodiac_score, args.confidence_score)
            df_db_links_filtered = df_csifingerid_cosmic_annotations_filtering(df_sirius, links=args.db_links)
            df_score_filtered = pd.concat([df_score_filtered, df_db_links_filtered], axis=0, ignore_index=True)

            #Prepare for virtual metabolization
            prepare_for_virtual_metabolization(df_score_filtered,
                                            compound_name='name',
                                            smiles_planar_column='smiles',
                                            drop_duplicated_structure=True, 
                                            use_planar_structure=True)

            print("SIRIUS input data processed.")
    else:
        print( 'No SIRIUS input given')

    print( '###USER-PROVDED COMPOUND LIST (Optional)')
    #Optional: Load and append extra compounds
    if args.extra_compounds_table_file:
        print( '')
        load_extra_compounds(args.extra_compounds_table_file)
        append_to_list_if_not_present(prepare_for_virtual_metabolization.list_compound_name, 
                                      prepare_for_virtual_metabolization.list_smiles, 
                                      load_extra_compounds.extra_compound_names, 
                                      load_extra_compounds.extra_compound_smiles)
    else:
        print('No user provided compound list were given')

    if args.debug:
        print("####Running in debug mode. Limiting to {} compounds. #####".format(args.max_compounds_debug))
        prepare_for_virtual_metabolization.list_compound_name = prepare_for_virtual_metabolization.list_compound_name[:args.max_compounds_debug]
        prepare_for_virtual_metabolization.list_smiles = prepare_for_virtual_metabolization.list_smiles[:args.max_compounds_debug]

    if args.run_sygma:
        print( '')
        print( '')
        print( '###RUNNING SyGMa - PLEASE WAIT ...')
        with CaptureOutput() as captured:
            run_sygma_batch(prepare_for_virtual_metabolization.list_smiles, 
                            prepare_for_virtual_metabolization.list_compound_name, 
                            args.phase_1_cycle, args.phase_2_cycle, args.top_sygma_candidates, 
                            dynamic_string, 'Compound_Name')

        filtered_output = captured.get_filtered_output()
        print(filtered_output)

        display(Markdown(run_sygma_batch.markdown_link_sygma))
        print('Results are at: '+run_sygma_batch.file_name_sygma)
        display(Markdown(run_sygma_batch.markdown_link_sygma_nap))
        print('Results are at: '+run_sygma_batch.file_name_sygma_nap)
        display(Markdown(run_sygma_batch.markdown_link_sygma_sirius))
        print('Results are at: '+run_sygma_batch.file_name_sygma_sirius)

    #Optional: Run BioTransformation
    if args.run_biotransformer:
        preparation = False
        print( '')
        print( '')
        print( '###PREPARING THE SETUP FOR BioTransformer3 - PLEASE WAIT (slow)...')

        try:
            with CaptureOutput() as captured_prep:
                prepare_for_bio3(args.type_of_biotransformation, prepare_for_virtual_metabolization.list_smiles)
            filtered_output_prep = captured_prep.get_filtered_output()
            print(filtered_output_prep)
            preparation = True
        except Exception as e:
            print("Error while running prepare_for_bio3: {}".format(e))
        
        print( '')
        print( '')
        print( '###RUNNING BioTransformer3 - PLEASE WAIT (slow)...')
        if preparation == True:
            with CaptureOutput() as captured:
                run_biotransformer3(args.mode, prepare_for_virtual_metabolization.list_smiles, 
                                    prepare_for_virtual_metabolization.list_compound_name,
                                    args.type_of_biotransformation, args.number_of_steps, dynamic_string)
            filtered_output = captured.get_filtered_output()
            print(filtered_output)
        else:
            print("Biotransformer3 was not run due to an error in the preparation step.")
       
        display(Markdown(run_biotransformer3.markdown_link_biotransf))
        print('Results are at: '+run_biotransformer3.file_name_biotransf)
        display(Markdown(run_biotransformer3.markdown_link_biotransf_nap))
        print('Results are at: '+run_biotransformer3.file_name_biotransf_nap)
        display(Markdown(run_biotransformer3.markdown_link_biotransf_sirius))
        print('Results are at: '+run_biotransformer3.file_name_biotransf_sirius)

    print( '')
    logging.info("####vm_NAP script finished successfully !")
    logging.info("##Download the results with the button below and proceed with NAP and/or SIRIUS ")
    

def apply_filtering(df_annotations, compound_name_to_keep):
    list_compounds = set(df_annotations['Compound_Name'])
    print(list_compounds)
    if compound_name_to_keep is None:
        return df_annotations
    elif compound_name_to_keep:
        print('After filtering')
        list_compounds = set(f_annotations_filtered['Compound_Name'])
        print(list_compounds)
        return df_annotations_filtered(df_annotations, compound_name=compound_name_to_keep)

def validate_mode_arg(value):
    allowed_modes = ['standard', 'btType']  #Replace with your actual mode values
    if value in allowed_modes or value.startswith('-k'):
        return value
    else:
        raise argparse.ArgumentTypeError("Invalid mode. For custom modes starting with '-k', please refer to https://bitbucket.org/wishartlab/biotransformer3.0jar/src/master/")

def positive_int_limited(value):
    min_value = 1
    max_value = 3
    try:
        ivalue = int(value)
        if ivalue < min_value or ivalue > max_value:
            raise argparse.ArgumentTypeError(f"Value must be between {min_value} and {max_value}")
        return ivalue
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid integer value")

#Wrapper function to decide which main function to call
def run_main():

    if len(sys.argv) == 1:
        #No arguments provided, display help and exit
        print("No arguments provided. Displaying help:")
        display_help()
        sys.exit(1)

    else:
        #Running in command-line
        parser = argparse.ArgumentParser(
        description="vm_NAP processing: A tool for integrating molecular networking, virtual metabolism, and annotation propagation for xenobiotic metabolites.",
        epilog="Example usage:\n"
               "  python vm_NAP_processing.py --run_biotransformer --type_of_biotransformation='hgut' --debug\n"
               "  python vm_NAP_processing.py --debug --extra_compounds_table_file='input/extra_compounds-UTF8.tsv' --run_biotransformer\n"
               "  python vm_NAP_processing.py --job_id='bbee697a63b1400ea585410fafc95723' --ionisation_mode='neg' --run_sygma\n"
               "  python vm_NAP_processing.py --job_id='false' --extra_compounds_table_file='input/extra_compounds.tsv' --run_sygma --run_biotransformer\n"
               "  python vm_NAP_processing.py --debug --run_sygma --phase_1_cycle=2 --phase_2_cycle=1\n"
               "  python vm_NAP_processing.py --debug --run_sygma --sirius_input_file= input/compound_identifications.tsv\n"
               "  python vm_NAP_processing.py --job_id='false' --extra_compounds_table_file='input/extra_compounds.tsv' --run_biotransformer --mode='standard'\n\n"
               "Example usage with -k flag:\n"
               "  python vm_NAP_processing.py --run_biotransformer --mode='-k pred -b superbio -a'\n"
               "  python vm_NAP_processing.py --run_biotransformer --mode='-k pred -b allHuman -s 2 -cm 3'\n"
               "  python vm_NAP_processing.py --run_biotransformer --mode='-k cid -b allHuman -s 2 -m \"292.0946;304.0946\" -t 0.01 -a'\n"
               "  python vm_NAP_processing.py --run_biotransformer --mode='-k pred -q \"cyp450:2; phaseII:1\"'",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )

        #parser.add_argument("--streamlit", action='store_true', default=False, help="Run the streamlit instance instead of the commandline")

        #GNPS job parameters
        gnps_group = parser.add_argument_group('GNPS Parameters')
        gnps_group.add_argument("--job_id", type=str, default='False', help="GNPS job ID for downloading and processing GNPS data ('bbee697a63b1400ea585410fafc95723'). The value 'False' can be used to skip this step")
        gnps_group.add_argument("--ionisation_mode", type=str, default='pos', choices=['pos', 'neg'], help="Ionisation mode used in the GNPS job (positive or negative).")
        gnps_group.add_argument("--max_ppm_error", type=int, default=10, help="Maximum allowed parts-per-million error for spectral matching.")
        gnps_group.add_argument("--min_cosine", type=float, default=0.6, help="Minimum cosine score for considering spectral matches.")
        gnps_group.add_argument("--shared_peaks", type=int, default=3, help="Minimum number of shared peaks for considering spectral matches.")
        gnps_group.add_argument("--max_spec_charge", type=int, default=2, help="Maximum charge state of spectra to consider.")

        #Metadata filtering
        metadata_group = parser.add_argument_group('Metadata Filtering')
        metadata_group.add_argument("--compound_name_to_keep", nargs='*', default=None, help="List of compound names to keep for filtering. If not provided, no filtering is applied.")

        #Extra structure file
        extra_compounds_group = parser.add_argument_group('Extra Compounds')
        extra_compounds_group.add_argument("--extra_compounds_table_file", type=str, default=None, help="Path to a file containing extra compounds to be included in the analysis.")

        #SIRIUS Parameters
        sirius_group = parser.add_argument_group('SIRIUS Parameters')
        sirius_group.add_argument("--sirius_input_file", type=str, default=None, help="Path to the SIRIUS structure annotation file (compound_annotations.tsv).")
        sirius_group.add_argument("--zodiac_score", type=float, default=0.7, help="Zodiac score threshold for filtering SIRIUS results.")
        sirius_group.add_argument("--confidence_score", type=float, default=0.1, help="Confidence score threshold for filtering SIRIUS results.")
        sirius_group.add_argument("--db_links", type=str, default='KEGG|HMDB', help="Database links for filtering SIRIUS results.")

        #Structure parameters
        structure_group = parser.add_argument_group('Structure Parameters')
        structure_group.add_argument("--use_planar_structure_boolean", type=bool, default=True, help="Flag to use planar structures for virtual metabolization.")

        #Metabolisation parameters
        metabolisation_group = parser.add_argument_group('Metabolisation Parameters')
        metabolisation_group.add_argument("--run_sygma", action='store_true', default=True, help="Flag to run SyGMa for virtual metabolism prediction.")
        metabolisation_group.add_argument("--phase_1_cycle", type=positive_int_limited, default=1, help="Number of phase 1 metabolism cycles to simulate in SyGMa.")
        metabolisation_group.add_argument("--phase_2_cycle", type=positive_int_limited, default=1, help="Number of phase 2 metabolism cycles to simulate in SyGMa.")
        metabolisation_group.add_argument("--top_sygma_candidates", type=int, default=10, help="Number of top SyGMa metabolite candidates to consider.")

        #BioTransformer3
        biotransformer_group = parser.add_argument_group('BioTransformer Parameters')
        biotransformer_group.add_argument("--run_biotransformer", action='store_true', help="Flag to run BioTransformer for metabolism prediction.")
        biotransformer_group.add_argument("--mode", type=validate_mode_arg, default='btType', help="Mode for running BioTransformer. Use 'btType', or custom mode string input for Biotransformer starting with '-k'.")
        biotransformer_group.add_argument("--type_of_biotransformation", type=str, choices=['ecbased', 'cyp450', 'phaseII', 'hgut', 'superbio', 'allHuman', 'envimicro'], default='allHuman', help="Type of biotransformation to simulate in BioTransformer.")
        biotransformer_group.add_argument("--number_of_steps", type=positive_int_limited, default=1, help="Number of biotransformation steps to simulate in BioTransformer.")

        #Debug mode
        parser.add_argument("--debug", action='store_true', help="Run in debug mode with limited data for testing purposes.")
        parser.add_argument("--max_compounds_debug", type=int, default=3, 
                        help="Maximum number of compounds to process in debug mode.")

        args = parser.parse_args()
        main(args)


def display_help():
    #Define your help message here
    help_message = """ For help run:
    python vm_NAP_processing.py --help
    """

    print(help_message)

if __name__ == "__main__":
    run_main()
