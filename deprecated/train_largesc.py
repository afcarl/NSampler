"""Training file for large datasets: """

import os
import sys
import timeit

import cPickle as pkl
import h5py
import numpy as np
import tensorflow as tf

import sr_preprocess_largesc as pp
import sr_utility
import models


def define_checkpoint(opt):
    nn_file = name_network(opt)
    checkpoint_dir = os.path.join(opt['save_dir'], nn_file)
    if not os.path.exists(checkpoint_dir):
        os.makedirs(checkpoint_dir)
    return checkpoint_dir

def define_logdir(opt):
    nn_file = name_network(opt)
    checkpoint_dir = os.path.join(opt['log_dir'], nn_file)
    if not os.path.exists(checkpoint_dir):
        os.makedirs(checkpoint_dir)
    return checkpoint_dir

def name_network(opt):
    """given inputs, return the model name."""
    optim = opt['optimizer'].__name__

    nn_tuple = (opt['method'], opt['upsampling_rate'],
                2*opt['input_radius']+1,
                2*opt['receptive_field_radius']+1,
                (2*opt['output_radius']+1)*opt['upsampling_rate'],
                optim, str(opt['dropout_rate']), opt['transform_opt'],)
    nn_str = '%s_us=%i_in=%i_rec=%i_out=%i_opt=%s_drop=%s_prep=%s_'
    nn_tuple += (opt['cohort'], opt['no_subjects'],
                 opt['subsampling_rate'], opt['patchlib_idx'])
    nn_str += '%s_TS%i_Subsample%03i_%03i'

    return nn_str % nn_tuple


def update_best_loss(this_loss, bests, iter_, current_step):
    bests['counter'] += 1
    if this_loss < bests['val_loss']:
        bests['counter'] = 0
        bests['val_loss'] = this_loss
        bests['iter_'] = iter_
        bests['step'] = current_step + 1
    return bests


def update_best_loss_epoch(this_loss, bests, current_step):
    if this_loss < bests['val_loss_save']:
        bests['val_loss_save'] = this_loss
        bests['step_save'] = current_step + 1
    return bests


def save_model(opt, sess, saver, global_step, model_details):
    checkpoint_dir = opt['checkpoint_dir']
    checkpoint_prefix = os.path.join(checkpoint_dir, "model")
    save_path = saver.save(sess, checkpoint_prefix, global_step=global_step)
    print("Model saved in file: %s" % save_path)
    with open(os.path.join(checkpoint_dir, 'settings.pkl'), 'wb') as fp:
        pkl.dump(model_details, fp, protocol=pkl.HIGHEST_PROTOCOL)
    print('Model details saved')


def train_cnn(opt):
    # ------------------ Load inputs from op ------------------------:
    # Network details:
    optimizer = opt['optimizer']
    optimisation_method = opt['optimizer'].__name__

    dropout_rate = opt['dropout_rate']
    learning_rate = opt['learning_rate']
    L1_reg = opt['L1_reg']
    L2_reg = opt['L2_reg']
    n_epochs = opt['n_epochs']
    batch_size = opt['batch_size']
    validation_fraction = opt['validation_fraction']
    train_fraction = int(1.0 - validation_fraction)
    shuffle = opt['shuffle']

    method = opt['method']
    n_h1 = opt['n_h1']
    n_h2 = opt['n_h2']
    n_h3 = opt['n_h3']
    cohort = opt['cohort']

    # Data details:
    no_subjects = opt['no_subjects']
    subsampling_rate = opt['subsampling_rate']

    # Input/Output details:
    upsampling_rate = opt['upsampling_rate']
    no_channels = opt['no_channels']
    input_radius = opt['input_radius']
    receptive_field_radius = opt['receptive_field_radius']
    output_radius = ((2*input_radius - 2*receptive_field_radius + 1) // 2)
    opt['output_radius'] = output_radius
    transform_opt = opt['transform_opt']

    # Dir:
    data_dir = opt['data_dir']  # '../data/'
    save_dir = opt['save_dir']

    # Set the directory for saving checkpoints:
    checkpoint_dir = define_checkpoint(opt)
    log_dir = define_logdir(opt)
    opt["checkpoint_dir"] = checkpoint_dir

    # exit if the network has already been trained:
    if os.path.exists(os.path.join(checkpoint_dir, 'settings.pkl')):
        print('Network already trained. Move on to next.')
        return

    # -------------------------load data------------------------------------:
    data, n_train, n_valid = pp.load_hdf5(opt)
    opt['train_noexamples'] = n_train
    opt['valid_noexamples'] = n_valid
    in_shape = data['in']['X'].shape[1:]
    out_shape = data['out']['X'].shape[1:]

    # --------------------------- Define the model--------------------------:
    #  define input and output:
    with tf.name_scope('input'):
        x = tf.placeholder(tf.float32, [None,
                                        2 * input_radius + 1,
                                        2 * input_radius + 1,
                                        2 * input_radius + 1,
                                        no_channels],
                           name='lo_res')
        y = tf.placeholder(tf.float32, [None,
                                        2 * output_radius + 1,
                                        2 * output_radius + 1,
                                        2 * output_radius + 1,
                                        no_channels * (upsampling_rate ** 3)],
                           name='hi_res')
    with tf.name_scope('learning_rate'):
        lr = tf.placeholder(tf.float32, [], name='learning_rate')

    with tf.name_scope('dropout'):
        keep_prob = tf.placeholder(tf.float32)  # keep probability for dropout

    global_step = tf.Variable(0, name="global_step", trainable=False)

    # Build model and loss function
    y_pred, y_std, cost = models.inference(method, x, keep_prob, opt)

    # Define gradient descent op
    with tf.name_scope('train'):
        optim = opt['optimizer'](learning_rate=lr)
        train_step = optim.minimize(cost, global_step=global_step)

    with tf.name_scope('accuracy'):
        mse = tf.reduce_mean(tf.square(data['out']['std'] * (y - y_pred)))
        tf.summary.scalar('mse', mse)

    # -------------------------- Start training -----------------------------:
    saver = tf.train.Saver()
    print('... training')
    with tf.Session() as sess:
        # Run the Op to initialize the variables.
        init = tf.initialize_all_variables()
        sess.run(init)

        # Merge all the summaries and write them out to ../network_name/log
        merged = tf.summary.merge_all()
        train_writer = tf.train.SummaryWriter(log_dir + '/train', sess.graph)
        valid_writer = tf.train.SummaryWriter(log_dir + '/valid')

        # Compute number of minibatches for training, validation and testing
        n_train_batches = n_train // batch_size
        n_valid_batches = n_valid // batch_size

        # Define some counters
        test_score = 0
        start_time = timeit.default_timer()
        epoch = 0
        done_looping = False
        iter_valid = 0
        total_val_loss_epoch = 0
        total_tr_loss_epoch = 0
        lr_ = opt['learning_rate']

        bests = {}
        bests['val_loss'] = np.inf  # best valid loss itr wise
        bests['val_loss_save'] = np.inf  # best valid loss in saved checkpoints
        bests['iter_'] = 0
        bests['step'] = 0
        bests['step_save'] = 0  # global step for the best saved model
        bests['counter'] = 0
        bests['counter_thresh'] = 10
        validation_frequency = n_train_batches
        save_frequency = 1

        model_details = opt.copy()
        model_details.update(bests)
        model_details['epoch_tr_loss'] = []
        model_details['epoch_val_loss'] = []

        while (epoch < n_epochs) and (not done_looping):
            epoch += 1
            start_time_epoch = timeit.default_timer()
            if epoch % 50 == 0:
                lr_ = lr_ / 10.

            if shuffle:
                tindices = np.random.permutation(n_train)
                vindices = np.random.permutation(n_valid)
            else:
                indices = np.arange(data['in']['X'].shape[0])
                # tindices = np.arange(n_train)
                # vindices = np.arange(n_valid)

            for mi in xrange(n_train_batches):
                # Select minibatches using a slice object---consider
                # multi-threading for speed if this is too slow
                if shuffle:
                    tidx = np.s_[np.sort(tindices[mi*batch_size:
                                 (mi+1)*batch_size]),...]
                    vidx = np.s_[np.sort(vindices[mi*batch_size:
                                 (mi+1)*batch_size]+n_train),...]
                else:
                    tidx = np.s_[indices[mi * batch_size:
                                 (mi + 1) * batch_size], ...]
                    vidx = np.s_[indices[mi * batch_size + n_train:
                                 (mi + 1) * batch_size + n_train], ...]

                xt = pp.dict_whiten(data, 'in', tidx)  # training minbatch
                yt = pp.dict_whiten(data, 'out', tidx)
                xv = pp.dict_whiten(data, 'in', vidx)  # validation minbatch
                yv = pp.dict_whiten(data, 'out', vidx)
                current_step = tf.train.global_step(sess, global_step)

                # print("Shape of xt, yt, xv, yv:%s, %s, %s, %s" % (xt.shape, yt.shape, xv.shape, yv.shape))

                # train op and loss
                fd_t={x: xt, y: yt, lr: lr_, keep_prob: 1.-dropout_rate}
                __, tr_loss = sess.run([train_step, mse], feed_dict=fd_t)
                total_tr_loss_epoch += tr_loss

                # valid loss
                fd_v = {x: xv, y: yv, keep_prob: 1.-dropout_rate}
                va_loss = sess.run(mse, feed_dict=fd_v)
                total_val_loss_epoch += va_loss

                # iteration number
                iter_ = (epoch - 1) * n_train_batches + mi
                iter_valid += 1

                # Print out current progress
                if (iter_ + 1) % (validation_frequency/10) == 0:
                    summary_t = sess.run(merged, feed_dict=fd_t)
                    summary_v = sess.run(merged, feed_dict=fd_v)
                    train_writer.add_summary(summary_t, iter_ + 1)
                    valid_writer.add_summary(summary_v, iter_ + 1)
                    vl = np.sqrt(va_loss*10**10)
                    sys.stdout.flush()
                    sys.stdout.write('\tvalidation error: %.2f\r' % (vl,))

                if (iter_ + 1) % validation_frequency == 0:
                    # Print out the errors for each epoch:
                    this_val_loss = total_val_loss_epoch/iter_valid
                    this_tr_loss = total_tr_loss_epoch/iter_valid
                    end_time_epoch = timeit.default_timer()

                    model_details['epoch_val_loss'].append(this_val_loss)
                    model_details['epoch_tr_loss'].append(this_tr_loss)

                    print('\nEpoch %i, minibatch %i/%i:\n' \
                          '\ttraining error (rmse) %f times 1E-5\n' \
                          '\tvalidation error (rmse) %f times 1E-5\n' \
                          '\ttook %f secs' % (epoch, mi + 1, n_train_batches,
                        np.sqrt(this_tr_loss*10**10),
                        np.sqrt(this_val_loss*10**10),
                        end_time_epoch - start_time_epoch))

                    bests = update_best_loss(this_val_loss, bests, iter_,
                                             current_step)

                    # Start counting again:
                    total_val_loss_epoch = 0
                    total_tr_loss_epoch = 0
                    iter_valid = 0
                    start_time_epoch = timeit.default_timer()

            if epoch % save_frequency == 0:
                if this_val_loss < bests['val_loss_save']:
                    bests = update_best_loss_epoch(this_val_loss, bests, current_step)
                    model_details.update(bests)
                    save_model(opt, sess, saver, global_step, model_details)

        # close the summary writers:
        train_writer.close()
        valid_writer.close()

        # Display the best results:
        print(('\nOptimization complete. Best validation score of %f  '
               'obtained at iteration %i') %
              (np.sqrt(bests['val_loss']*10**10), bests['step']))

        # Display the best results for saved models:
        print(('\nOptimization complete. Best validation score of %f  '
               'obtained at iteration %i') %
              (np.sqrt(bests['val_loss_save'] * 10 ** 10), bests['step_save']))

        end_time = timeit.default_timer()
        time_train = end_time - start_time
        print('Training done!!! It took %f secs.' % time_train)
