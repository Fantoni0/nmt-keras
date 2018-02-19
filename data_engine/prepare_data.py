from keras_wrapper.dataset import Dataset, saveDataset, loadDataset
import logging

logging.basicConfig(level=logging.DEBUG, format='[%(asctime)s] %(message)s', datefmt='%d/%m/%Y %H:%M:%S')


def update_dataset_from_file(ds,
                             input_text_filename,
                             params,
                             splits=None,
                             output_text_filename=None,
                             remove_outputs=False,
                             compute_state_below=False,
                             recompute_references=False):
    """
    Updates the dataset instance from a text file according to the given params.
    Used for sampling

    :param ds: Dataset instance
    :param input_text_filename: Source language sentences
    :param params: Parameters for building the dataset
    :param splits: Splits to sample
    :param output_text_filename: Target language sentences
    :param remove_outputs: Remove outputs from dataset (if True, will ignore the output_text_filename parameter)
    :param compute_state_below: Compute state below input (shifted target text for professor teaching)

    :return: Dataset object with the processed data
    """

    # If we are using Character NMT ONLY at encoder level. We'll need different tokenization functions
    if params['MAX_INPUT_WORD_LEN'] > 0:
        conditional_tok = 'tokenize_none'
    else:
        conditional_tok = params['TOKENIZATION_METHOD']

    if output_text_filename is None:
        recompute_references = False

    if splits is None:
        splits = ['val']

    for split in splits:
        if remove_outputs:
            ds.removeOutput(split,
                            type='dense_text' if 'sparse' in params['LOSS'] else 'text',
                            id=params['OUTPUTS_IDS_DATASET'][0])
            recompute_references = False

        elif output_text_filename is not None:
            ds.setOutput(output_text_filename,
                         split,
                         type='dense_text' if 'sparse' in params['LOSS'] else 'text',
                         id=params['OUTPUTS_IDS_DATASET'][0],
                         tokenization=conditional_tok,
                         build_vocabulary=False,
                         pad_on_batch=params['PAD_ON_BATCH'],
                         fill=params.get('FILL_TARGET', 'end'),
                         sample_weights=params['SAMPLE_WEIGHTS'],
                         max_text_len=params['MAX_OUTPUT_TEXT_LEN'],
                         max_words=params['OUTPUT_VOCABULARY_SIZE'],
                         min_occ=params['MIN_OCCURRENCES_OUTPUT_VOCAB'],
                         bpe_codes=params.get('BPE_CODES_PATH', None),
                         overwrite_split=True)

        # INPUT DATA
        ds.setInput(input_text_filename,
                    split,
                    type='text',
                    id=params['INPUTS_IDS_DATASET'][0],
                    tokenization= params.get('TOKENIZATION_METHOD', 'tokenize_none'),
                    build_vocabulary=False,
                    pad_on_batch=params.get('PAD_ON_BATCH', True),
                    fill=params.get('FILL', 'end'),
                    fill_char=params.get('FILL_CHAR', 'end'),
                    char_bpe=params['CHAR_BPE'],
                    max_text_len=params.get('MAX_INPUT_TEXT_LEN', 100),
                    max_word_len=params['MAX_INPUT_WORD_LEN'],
                    max_words=params.get('INPUT_VOCABULARY_SIZE', 0),
                    min_occ=params.get('MIN_OCCURRENCES_INPUT_VOCAB', 0),
                    bpe_codes=params.get('BPE_CODES_PATH', None),
                    overwrite_split=True)
        if compute_state_below and output_text_filename is not None:
            # INPUT DATA
            ds.setInput(output_text_filename,
                        split,
                        type='text',
                        id=params['INPUTS_IDS_DATASET'][1],
                        pad_on_batch=params.get('PAD_ON_BATCH', True),
                        tokenization=conditional_tok,
                        build_vocabulary=False,
                        offset=1,
                        fill=params['FILL'],
                        fill_char=params['FILL'],
                        max_text_len=params['MAX_INPUT_TEXT_LEN'],
                        max_words=params['INPUT_VOCABULARY_SIZE'],
                        char_bpe=params['CHAR_BPE'],
                        min_occ=params['MIN_OCCURRENCES_OUTPUT_VOCAB'],
                        bpe_codes=params.get('BPE_CODES_PATH', None),
                        overwrite_split=True)
        else:
            ds.setInput(None,
                        split,
                        type='ghost',
                        id=params['INPUTS_IDS_DATASET'][-1],
                        required=False,
                        overwrite_split=True)

        if params['ALIGN_FROM_RAW']:
            ds.setRawInput(input_text_filename,
                           split,
                           type='file-name',
                           id='raw_' + params['INPUTS_IDS_DATASET'][0],
                           overwrite_split=True)

        # If we had multiple references per sentence
        if recompute_references:
            keep_n_captions(ds, repeat=1, n=1, set_names=params['EVAL_ON_SETS'])

    return ds


def build_dataset(params):
    """
    Builds (or loads) a Dataset instance.
    :param params: Parameters specifying Dataset options
    :return: Dataset object
    """

    if params['REBUILD_DATASET']:  # We build a new dataset instance
        if params['VERBOSE'] > 0:
            silence = False
            logging.info(
                'Building ' + params['TASK_NAME'] + '_' + params['SRC_LAN'] + params['TRG_LAN'] + ' dataset')
        else:
            silence = True

        # If we are using Character NMT ONLY at encoder level. We'll need different tokenization functions
        if params['MAX_INPUT_WORD_LEN'] > 0:
            conditional_tok = 'tokenize_none'
        else:
            conditional_tok = params['TOKENIZATION_METHOD']

        base_path = params['DATA_ROOT_PATH']
        name = params['TASK_NAME'] + '_' + params['SRC_LAN'] + params['TRG_LAN']
        ds = Dataset(name, base_path, silence=silence)

        # OUTPUT DATA
        # Let's load the train, val and test splits of the target language sentences (outputs)
        #    the files include a sentence per line.
        ds.setOutput(base_path + '/' + params['TEXT_FILES']['train'] + params['TRG_LAN'],
                     'train',
                     type='dense_text' if 'sparse' in params['LOSS'] else 'text',
                     id=params['OUTPUTS_IDS_DATASET'][0],
                     tokenization=conditional_tok,
                     build_vocabulary=True,
                     pad_on_batch=params['PAD_ON_BATCH'],
                     fill=params.get('FILL_TARGET', 'end'),
                     fill_char=params.get('FILL_TARGET', 'end'),
                     sample_weights=params['SAMPLE_WEIGHTS'],
                     max_text_len=params['MAX_OUTPUT_TEXT_LEN'],
                     char_bpe=params['CHAR_BPE'],
                     max_words=params['OUTPUT_VOCABULARY_SIZE'],
                     min_occ=params['MIN_OCCURRENCES_OUTPUT_VOCAB'],
                     bpe_codes=params.get('BPE_CODES_PATH', None))
        if params['ALIGN_FROM_RAW'] and not params['HOMOGENEOUS_BATCHES']:
            ds.setRawOutput(base_path + '/' + params['TEXT_FILES']['train'] + params['TRG_LAN'],
                            'train',
                            type='file-name',
                            id='raw_' + params['OUTPUTS_IDS_DATASET'][0])

        for split in ['val', 'test']:
            if params['TEXT_FILES'].get(split) is not None:
                ds.setOutput(base_path + '/' + params['TEXT_FILES'][split] + params['TRG_LAN'],
                             split,
                             type='dense_text' if 'sparse' in params['LOSS'] else 'text',
                             id=params['OUTPUTS_IDS_DATASET'][0],
                             pad_on_batch=params['PAD_ON_BATCH'],
                             fill=params.get('FILL_TARGET', 'end'),
                             fill_char=params.get('FILL_TARGET', 'end'),
                             tokenization=conditional_tok,
                             sample_weights=params['SAMPLE_WEIGHTS'],
                             max_text_len=params['MAX_OUTPUT_TEXT_LEN'],
                             max_words=params['OUTPUT_VOCABULARY_SIZE'],
                             bpe_codes=params.get('BPE_CODES_PATH', None))
                if params['ALIGN_FROM_RAW'] and not params['HOMOGENEOUS_BATCHES']:
                    ds.setRawOutput(base_path + '/' + params['TEXT_FILES'][split]   + params['TRG_LAN'],
                                    split,
                                    type='file-name',
                                    id='raw_' + params['OUTPUTS_IDS_DATASET'][0])

        # INPUT DATA
        # We must ensure that the 'train' split is the first (for building the vocabulary)
        for split in ['train', 'val', 'test']:
            if params['TEXT_FILES'].get(split) is not None:
                if split == 'train':
                    build_vocabulary = True
                else:
                    build_vocabulary = False
                ds.setInput(base_path + '/' + params['TEXT_FILES'][split] + params['SRC_LAN'],
                            split,
                            type='text',
                            id=params['INPUTS_IDS_DATASET'][0],
                            pad_on_batch=params.get('PAD_ON_BATCH', True),
                            tokenization=params.get('TOKENIZATION_METHOD', 'tokenize_none'),
                            build_vocabulary=build_vocabulary,
                            fill=params['FILL'],
                            fill_char=params.get('FILL_CHAR', 'end'),
                            max_text_len=params['MAX_INPUT_TEXT_LEN'],
                            max_word_len=params['MAX_INPUT_WORD_LEN'],
                            char_bpe=params['CHAR_BPE'],
                            max_words=params['INPUT_VOCABULARY_SIZE'],
                            min_occ=params['MIN_OCCURRENCES_INPUT_VOCAB'],
                            bpe_codes=params.get('BPE_CODES_PATH', None))

                if len(params['INPUTS_IDS_DATASET']) > 1: #State_below
                    if 'train' in split:
                        ds.setInput(base_path + '/' + params['TEXT_FILES'][split] + params['TRG_LAN'],
                                    split,
                                    type='text',
                                    id=params['INPUTS_IDS_DATASET'][1],
                                    required=False,
                                    tokenization=conditional_tok,
                                    pad_on_batch=params['PAD_ON_BATCH'],
                                    build_vocabulary=params['OUTPUTS_IDS_DATASET'][0],
                                    offset=1,
                                    fill=params.get('FILL', 'end'),
                                    max_text_len=params['MAX_OUTPUT_TEXT_LEN'],
                                    max_word_len=0,
                                    char_bpe=params['CHAR_BPE'],
                                    max_words=params['OUTPUT_VOCABULARY_SIZE'],
                                    bpe_codes=params.get('BPE_CODES_PATH', None))
                    else:
                        ds.setInput(None,
                                    split,
                                    type='ghost',
                                    id=params['INPUTS_IDS_DATASET'][-1],
                                    required=False)
                if params.get('ALIGN_FROM_RAW', True) and not params.get('HOMOGENEOUS_BATCHES', False):
                    ds.setRawInput(base_path + '/' + params['TEXT_FILES'][split] + params['SRC_LAN'],
                                   split,
                                   type='file-name',
                                   id='raw_' + params['INPUTS_IDS_DATASET'][0])

        if params.get('POS_UNK', False):
            if params.get('HEURISTIC', 0) > 0:
                ds.loadMapping(params['MAPPING'])

        # If we had multiple references per sentence
        keep_n_captions(ds, repeat=1, n=1, set_names=params['EVAL_ON_SETS'])

        # We have finished loading the dataset, now we can store it for using it in the future
        saveDataset(ds, params['DATASET_STORE_PATH'])

    else:
        # We can easily recover it with a single line
        ds = loadDataset(params['DATASET_STORE_PATH'] + '/Dataset_' + params['DATASET_NAME']
                         + '_' + params['SRC_LAN'] + params['TRG_LAN'] + '.pkl')

        # If we had multiple references per sentence
        keep_n_captions(ds, repeat=1, n=1, set_names=params['EVAL_ON_SETS'])

    return ds


def keep_n_captions(ds, repeat, n=1, set_names=None):
    """
    Keeps only n captions per image and stores the rest in dictionaries for a later evaluation
    :param ds: Dataset object
    :param repeat: Number of input samples per output
    :param n: Number of outputs to keep.
    :param set_names: Set name.
    :return:
    """

    n_samples = None
    X = None
    Y = None

    if set_names is None:
        set_names = ['val', 'test']
    for s in set_names:
        logging.info('Keeping ' + str(n) + ' captions per input on the ' + str(s) + ' set.')

        ds.extra_variables[s] = dict()
        exec ('n_samples = ds.len_' + s)

        # Process inputs
        for id_in in ds.ids_inputs:
            new_X = []
            if id_in in ds.optional_inputs:
                try:
                    exec ('X = ds.X_' + s)
                    for i in range(0, n_samples, repeat):
                        for j in range(n):
                            new_X.append(X[id_in][i + j])
                    exec ('ds.X_' + s + '[id_in] = new_X')
                except Exception:
                    pass
            else:
                exec ('X = ds.X_' + s)
                for i in range(0, n_samples, repeat):
                    for j in range(n):
                        new_X.append(X[id_in][i + j])
                exec ('ds.X_' + s + '[id_in] = new_X')
        # Process outputs
        for id_out in ds.ids_outputs:
            new_Y = []
            exec ('Y = ds.Y_' + s)
            dict_Y = dict()
            count_samples = 0
            for i in range(0, n_samples, repeat):
                dict_Y[count_samples] = []
                for j in range(repeat):
                    if j < n:
                        new_Y.append(Y[id_out][i + j])
                    dict_Y[count_samples].append(Y[id_out][i + j])
                count_samples += 1
            exec ('ds.Y_' + s + '[id_out] = new_Y')
            # store dictionary with img_pos -> [cap1, cap2, cap3, ..., capN]
            ds.extra_variables[s][id_out] = dict_Y

        new_len = len(new_Y)
        exec ('ds.len_' + s + ' = new_len')
        logging.info('Samples reduced to ' + str(new_len) + ' in ' + s + ' set.')
