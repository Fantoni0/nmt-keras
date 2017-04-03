import argparse
import ast
from timeit import default_timer as timer

from config import load_parameters
from data_engine.prepare_data import build_dataset
from keras_wrapper.cnn_model import loadModel, updateModel
from keras_wrapper.extra.callbacks import *
from model_zoo import TranslationModel
from utils.utils import update_parameters

logging.basicConfig(level=logging.DEBUG, format='[%(asctime)s] %(message)s', datefmt='%d/%m/%Y %H:%M:%S')
logger = logging.getLogger(__name__)


def train_model(params):
    """
    Training function. Sets the training parameters from params. Build or loads the model and launches the training.
    :param params: Dictionary of network hyperparameters.
    :return: None
    """

    if params['RELOAD'] > 0:
        logging.info('Resuming training.')

    check_params(params)

    # Load data
    dataset = build_dataset(params)
    params['INPUT_VOCABULARY_SIZE'] = dataset.vocabulary_len[params['INPUTS_IDS_DATASET'][0]]
    params['OUTPUT_VOCABULARY_SIZE'] = dataset.vocabulary_len[params['OUTPUTS_IDS_DATASET'][0]]

    # Build model
    if params['RELOAD'] == 0:  # build new model
        nmt_model = TranslationModel(params, type=params['MODEL_TYPE'], verbose=params['VERBOSE'],
                                     model_name=params['MODEL_NAME'], vocabularies=dataset.vocabulary,
                                     store_path=params['STORE_PATH'])
        dict2pkl(params, params['STORE_PATH'] + '/config')

        # Define the inputs and outputs mapping from our Dataset instance to our model
        inputMapping = dict()
        for i, id_in in enumerate(params['INPUTS_IDS_DATASET']):
            pos_source = dataset.ids_inputs.index(id_in)
            id_dest = nmt_model.ids_inputs[i]
            inputMapping[id_dest] = pos_source
        nmt_model.setInputsMapping(inputMapping)

        outputMapping = dict()
        for i, id_out in enumerate(params['OUTPUTS_IDS_DATASET']):
            pos_target = dataset.ids_outputs.index(id_out)
            id_dest = nmt_model.ids_outputs[i]
            outputMapping[id_dest] = pos_target
        nmt_model.setOutputsMapping(outputMapping)

    else:  # resume from previously trained model
        nmt_model = TranslationModel(params,
                                     type=params['MODEL_TYPE'],
                                     verbose=params['VERBOSE'],
                                     model_name=params['MODEL_NAME'],
                                     vocabularies=dataset.vocabulary,
                                     store_path=params['STORE_PATH'],
                                     set_optimizer=False,
                                     clear_dirs=False)
        nmt_model = updateModel(nmt_model, params['STORE_PATH'], params['RELOAD'])
        nmt_model.setParams(params)
        nmt_model.setOptimizer()

    # Callbacks
    callbacks = buildCallbacks(params, nmt_model, dataset)

    # Training
    total_start_time = timer()

    logger.debug('Starting training!')
    training_params = {'n_epochs': params['MAX_EPOCH'], 'batch_size': params['BATCH_SIZE'],
                       'homogeneous_batches': params['HOMOGENEOUS_BATCHES'], 'maxlen': params['MAX_OUTPUT_TEXT_LEN'],
                       'joint_batches': params['JOINT_BATCHES'],
                       'lr_decay': params['LR_DECAY'], 'lr_gamma': params['LR_GAMMA'],
                       'epochs_for_save': params['EPOCHS_FOR_SAVE'], 'verbose': params['VERBOSE'],
                       'eval_on_sets': params['EVAL_ON_SETS_KERAS'], 'n_parallel_loaders': params['PARALLEL_LOADERS'],
                       'extra_callbacks': callbacks, 'reload_epoch': params['RELOAD'], 'epoch_offset': params['RELOAD'],
                       'data_augmentation': params['DATA_AUGMENTATION'],
                       'patience': params.get('PATIENCE', 0),  # early stopping parameters
                       'metric_check': params.get('STOP_METRIC', None),
                       'eval_on_epochs': params.get('EVAL_EACH_EPOCHS', True),
                       'each_n_epochs': params.get('EVAL_EACH', 1),
                       'start_eval_on_epoch': params.get('START_EVAL_ON_EPOCH', 0)}
    nmt_model.trainNet(dataset, training_params)

    total_end_time = timer()
    time_difference = total_end_time - total_start_time
    logging.info('In total is {0:.2f}s = {1:.2f}m'.format(time_difference, time_difference / 60.0))


def apply_NMT_model(params):
    """
    Sample from a previously trained model.

    :param params: Dictionary of network hyperparameters.
    :return: None
    """

    # Load data
    dataset = build_dataset(params)
    params['INPUT_VOCABULARY_SIZE'] = dataset.vocabulary_len[params['INPUTS_IDS_DATASET'][0]]
    params['OUTPUT_VOCABULARY_SIZE'] = dataset.vocabulary_len[params['OUTPUTS_IDS_DATASET'][0]]

    # Load model
    nmt_model = loadModel(params['STORE_PATH'], params['RELOAD'])
    nmt_model.setOptimizer()

    for s in params["EVAL_ON_SETS"]:

        # Evaluate training
        extra_vars = {'language': params.get('TRG_LAN', 'en'),
                      'n_parallel_loaders': params['PARALLEL_LOADERS'],
                      'tokenize_f': eval('dataset.' + params['TOKENIZATION_METHOD']),
                      'detokenize_f': eval('dataset.' + params['DETOKENIZATION_METHOD']),
                      'apply_detokenization': params['APPLY_DETOKENIZATION'],
                      'tokenize_hypotheses': params['TOKENIZE_HYPOTHESES'],
                      'tokenize_references': params['TOKENIZE_REFERENCES']}
        vocab = dataset.vocabulary[params['OUTPUTS_IDS_DATASET'][0]]['idx2words']
        extra_vars[s] = dict()
        extra_vars[s]['references'] = dataset.extra_variables[s][params['OUTPUTS_IDS_DATASET'][0]]
        input_text_id = None
        vocab_src = None
        if params['BEAM_SIZE']:
            extra_vars['beam_size'] = params.get('BEAM_SIZE', 6)
            extra_vars['state_below_index'] = params.get('BEAM_SEARCH_COND_INPUT', -1)
            extra_vars['maxlen'] = params.get('MAX_OUTPUT_TEXT_LEN_TEST', 30)
            extra_vars['optimized_search'] = params.get('OPTIMIZED_SEARCH', True)
            extra_vars['model_inputs'] = params['INPUTS_IDS_MODEL']
            extra_vars['model_outputs'] = params['OUTPUTS_IDS_MODEL']
            extra_vars['dataset_inputs'] = params['INPUTS_IDS_DATASET']
            extra_vars['dataset_outputs'] = params['OUTPUTS_IDS_DATASET']
            extra_vars['normalize'] = params.get('NORMALIZE_SAMPLING', False)
            extra_vars['alpha_factor'] = params.get('ALPHA_FACTOR', 1.)
            extra_vars['pos_unk'] = params['POS_UNK']
            if params['POS_UNK']:
                extra_vars['heuristic'] = params['HEURISTIC']
                input_text_id = params['INPUTS_IDS_DATASET'][0]
                vocab_src = dataset.vocabulary[input_text_id]['idx2words']
                if params['HEURISTIC'] > 0:
                    extra_vars['mapping'] = dataset.mapping

        callback_metric = PrintPerformanceMetricOnEpochEndOrEachNUpdates(nmt_model,
                                                                         dataset,
                                                                         gt_id=params['OUTPUTS_IDS_DATASET'][0],
                                                                         metric_name=params['METRICS'],
                                                                         set_name=params['EVAL_ON_SETS'],
                                                                         batch_size=params['BATCH_SIZE'],
                                                                         each_n_epochs=params['EVAL_EACH'],
                                                                         extra_vars=extra_vars,
                                                                         reload_epoch=params['RELOAD'],
                                                                         is_text=True,
                                                                         input_text_id=input_text_id,
                                                                         save_path=nmt_model.model_path,
                                                                         index2word_y=vocab,
                                                                         index2word_x=vocab_src,
                                                                         sampling_type=params['SAMPLING'],
                                                                         beam_search=params['BEAM_SEARCH'],
                                                                         start_eval_on_epoch=params[
                                                                             'START_EVAL_ON_EPOCH'],
                                                                         write_samples=True,
                                                                         write_type=params['SAMPLING_SAVE_MODE'],
                                                                         eval_on_epochs=params['EVAL_EACH_EPOCHS'],
                                                                         save_each_evaluation=False,
                                                                         verbose=params['VERBOSE'])

        callback_metric.evaluate(params['RELOAD'], counter_name='epoch' if params['EVAL_EACH_EPOCHS'] else 'update')


def buildCallbacks(params, model, dataset):
    """
    Builds the selected set of callbacks run during the training of the model.

    :param params: Dictionary of network hyperparameters.
    :param model: Model instance on which to apply the callback.
    :param dataset: Dataset instance on which to apply the callback.
    :return:
    """

    callbacks = []

    if params['METRICS']:
        # Evaluate training
        extra_vars = {'language': params.get('TRG_LAN', 'en'),
                      'n_parallel_loaders': params['PARALLEL_LOADERS'],
                      'tokenize_f': eval('dataset.' + params.get('TOKENIZATION_METHOD', 'tokenize_none')),
                      'detokenize_f': eval('dataset.' + params.get('DETOKENIZATION_METHOD', 'detokenize_none')),
                      'apply_detokenization': params.get('APPLY_DETOKENIZATION', False),
                      'tokenize_hypotheses': params.get('TOKENIZE_HYPOTHESES', True),
                      'tokenize_references': params.get('TOKENIZE_REFERENCES', True)}

        vocab = dataset.vocabulary[params['OUTPUTS_IDS_DATASET'][0]]['idx2words']
        for s in params['EVAL_ON_SETS']:
            extra_vars[s] = dict()
            extra_vars[s]['references'] = dataset.extra_variables[s][params['OUTPUTS_IDS_DATASET'][0]]
        input_text_id = None
        vocab_src = None
        if params['BEAM_SIZE']:
            extra_vars['beam_size'] = params.get('BEAM_SIZE', 6)
            extra_vars['state_below_index'] = params.get('BEAM_SEARCH_COND_INPUT', -1)
            extra_vars['maxlen'] = params.get('MAX_OUTPUT_TEXT_LEN_TEST', 30)
            extra_vars['optimized_search'] = params.get('OPTIMIZED_SEARCH', True)
            extra_vars['model_inputs'] = params['INPUTS_IDS_MODEL']
            extra_vars['model_outputs'] = params['OUTPUTS_IDS_MODEL']
            extra_vars['dataset_inputs'] = params['INPUTS_IDS_DATASET']
            extra_vars['dataset_outputs'] = params['OUTPUTS_IDS_DATASET']
            extra_vars['normalize'] = params.get('NORMALIZE_SAMPLING', False)
            extra_vars['alpha_factor'] = params.get('ALPHA_FACTOR', 1.)
            extra_vars['pos_unk'] = params['POS_UNK']
            if params['POS_UNK']:
                extra_vars['heuristic'] = params['HEURISTIC']
                input_text_id = params['INPUTS_IDS_DATASET'][0]
                vocab_src = dataset.vocabulary[input_text_id]['idx2words']
                if params['HEURISTIC'] > 0:
                    extra_vars['mapping'] = dataset.mapping

        callback_metric = PrintPerformanceMetricOnEpochEndOrEachNUpdates(model,
                                                                         dataset,
                                                                         gt_id=params['OUTPUTS_IDS_DATASET'][0],
                                                                         metric_name=params['METRICS'],
                                                                         set_name=params['EVAL_ON_SETS'],
                                                                         batch_size=params['BATCH_SIZE'],
                                                                         each_n_epochs=params['EVAL_EACH'],
                                                                         extra_vars=extra_vars,
                                                                         reload_epoch=params['RELOAD'],
                                                                         is_text=True,
                                                                         input_text_id=input_text_id,
                                                                         index2word_y=vocab,
                                                                         index2word_x=vocab_src,
                                                                         sampling_type=params['SAMPLING'],
                                                                         beam_search=params['BEAM_SEARCH'],
                                                                         save_path=model.model_path,
                                                                         start_eval_on_epoch=params[
                                                                             'START_EVAL_ON_EPOCH'],
                                                                         write_samples=True,
                                                                         write_type=params['SAMPLING_SAVE_MODE'],
                                                                         eval_on_epochs=params['EVAL_EACH_EPOCHS'],
                                                                         save_each_evaluation=params[
                                                                             'SAVE_EACH_EVALUATION'],
                                                                         verbose=params['VERBOSE'])

        callbacks.append(callback_metric)

    if params['SAMPLE_ON_SETS']:
        # Write some samples
        extra_vars = {'language': params['TRG_LAN'], 'n_parallel_loaders': params['PARALLEL_LOADERS']}
        vocab_x = dataset.vocabulary[params['INPUTS_IDS_DATASET'][0]]['idx2words']
        vocab_y = dataset.vocabulary[params['OUTPUTS_IDS_DATASET'][0]]['idx2words']
        for s in params['EVAL_ON_SETS']:
            extra_vars[s] = dict()
            extra_vars[s]['references'] = dataset.extra_variables[s][params['OUTPUTS_IDS_DATASET'][0]]
            extra_vars[s]['tokenize_f'] = eval('dataset.' + params.get('TOKENIZATION_METHOD', 'tokenize_none'))
            extra_vars[s]['detokenize_f'] = eval('dataset.' + params.get('DETOKENIZATION_METHOD', 'detokenize_none'))
            extra_vars[s]['apply_detokenization'] = params.get('APPLY_DETOKENIZATION', False)
            extra_vars[s]['tokenize_hypotheses'] = params.get('TOKENIZE_HYPOTHESES', True)
            extra_vars[s]['tokenize_references'] = params.get('TOKENIZE_REFERENCES', True)

        if params['BEAM_SIZE']:
            extra_vars['beam_size'] = params['BEAM_SIZE']
            extra_vars['state_below_index'] = params.get('BEAM_SEARCH_COND_INPUT', -1)
            extra_vars['maxlen'] = params['MAX_OUTPUT_TEXT_LEN_TEST']
            extra_vars['optimized_search'] = params['OPTIMIZED_SEARCH']
            extra_vars['model_inputs'] = params['INPUTS_IDS_MODEL']
            extra_vars['model_outputs'] = params['OUTPUTS_IDS_MODEL']
            extra_vars['dataset_inputs'] = params['INPUTS_IDS_DATASET']
            extra_vars['dataset_outputs'] = params['OUTPUTS_IDS_DATASET']
            extra_vars['normalize'] = params['NORMALIZE_SAMPLING']
            extra_vars['alpha_factor'] = params['ALPHA_FACTOR']
            extra_vars['pos_unk'] = params['POS_UNK']
            if params['POS_UNK']:
                extra_vars['heuristic'] = params['HEURISTIC']
                if params['HEURISTIC'] > 0:
                    extra_vars['mapping'] = dataset.mapping

        callback_sampling = SampleEachNUpdates(model,
                                               dataset,
                                               gt_id=params['OUTPUTS_IDS_DATASET'][0],
                                               set_name=params['SAMPLE_ON_SETS'],
                                               n_samples=params['N_SAMPLES'],
                                               each_n_updates=params['SAMPLE_EACH_UPDATES'],
                                               extra_vars=extra_vars,
                                               reload_epoch=params['RELOAD'],
                                               batch_size=params['BATCH_SIZE'],
                                               is_text=True,
                                               index2word_x=vocab_x,  # text info
                                               index2word_y=vocab_y,  # text info
                                               print_sources=True,
                                               in_pred_idx=params['INPUTS_IDS_DATASET'][0],
                                               sampling_type=params['SAMPLING'],  # text info
                                               beam_search=params['BEAM_SEARCH'],
                                               start_sampling_on_epoch=params['START_SAMPLING'
                                                                              '_ON_EPOCH'],
                                               verbose=params['VERBOSE'])
        callbacks.append(callback_sampling)
    return callbacks


def check_params(params):
    """
    Checks some typical parameters and warns if something wrong was specified.
    :param params:  Model instance on which to apply the callback.
    :return: None
    """
    if params['POS_UNK']:
        assert params['OPTIMIZED_SEARCH'], 'Unknown words replacement requires ' \
                                           'to use the optimized search ("OPTIMIZED_SEARCH" parameter).'
    if params['SRC_PRETRAINED_VECTORS'] and params['SRC_PRETRAINED_VECTORS'][:-1] != '.npy':
        warnings.warn('It seems that the pretrained word vectors provided for the target text are not in npy format.'
                      'You should preprocess the word embeddings with the "utils/preprocess_*_word_vectors.py script.')

    if params['TRG_PRETRAINED_VECTORS'] and params['TRG_PRETRAINED_VECTORS'][:-1] != '.npy':
        warnings.warn('It seems that the pretrained word vectors provided for the target text are not in npy format.'
                      'You should preprocess the word embeddings with the "utils/preprocess_*_word_vectors.py script.')


def parse_args():
    parser = argparse.ArgumentParser("Train or sample NMT models")
    parser.add_argument("-c", "--config", required=False, help="Config pkl for loading the model configuration. "
                                                               "If not specified, hyperparameters "
                                                               "are read from config.py")
    parser.add_argument("-ds", "--dataset", required=False, help="Dataset instance with data")
    parser.add_argument("changes", nargs="*", help="Changes to config. "
                                                   "Following the syntax Key=Value",
                        default="")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    parameters = load_parameters()
    if args.config is not None:
        parameters = update_parameters(parameters, pkl2dict(args.config))
    try:
        for arg in args.changes:
            try:
                k, v = arg.split('=')
            except ValueError:
                print 'Overwritten arguments must have the form key=Value. \n Currently are: %s' % str(args.changes)
                exit(1)
            try:
                parameters[k] = ast.literal_eval(v)
            except:
                parameters[k] = v
    except ValueError:
        print 'Error processing arguments: (', k, ",", v, ")"
        exit(2)

    check_params(parameters)
    if parameters['MODE'] == 'training':
        logging.info('Running training.')
        train_model(parameters)
    elif parameters['MODE'] == 'sampling':
        logging.info('Running sampling.')
        apply_NMT_model(parameters)

    logging.info('Done!')
