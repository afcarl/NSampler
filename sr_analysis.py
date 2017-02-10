from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import numpy as np
from skimage.measure import compare_ssim as ssim
import nibabel as nib
from skimage.measure import compare_psnr as psnr
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.stats.stats import pearsonr
from scipy.stats import spearmanr

# Perform correlation analysis of two images:
def correlation_plot_and_analyse(img1, img2, mask, no_points,
                                 xlabel, ylabel, title, opt):
    """ plot a scatter plot of image 1 and image """

    if img1.shape!=img2.shape:
        print("shape of img1 and img2: %s and %s" %(img1.shape,img2.shape))
        raise ValueError("the size of img 1 and img 2 do not match")
    else:
        print('image size match up!')

    brain_ind = [(i, j, k) for i in xrange(img1.shape[0])
                           for j in xrange(img1.shape[1])
                           for k in xrange(img1.shape[2])
                           if mask[i, j, k] == True]

    ind_sub = random.sample(brain_ind, no_points)
    img1_samples, img2_samples = np.zeros((no_points,)), np.zeros((no_points,))
    for idx, (i,j,k) in enumerate(ind_sub):
        img1_samples[idx],img2_samples[idx] = img1[i,j,k],img2[i,j,k]

    # scatter plot
    scatter_plot_with_correlation_line(img1_samples, img2_samples)

    # Compute pearson correlation:
    r, p = pearsonr(img1_samples, img2_samples)
    s, p2 = spearmanr(img1_samples, img2_samples)
    pearson_info = 'pearson = %.2f, ' % (r,)
    spearman_info = 'spear = %.2f' % (s,)
    print(pearson_info)
    print(spearman_info)

    # labels:
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title+pearson_info+spearman_info)


# Plot one .nii against another .nii:
def plot_twonii(nii_1,nii_2, mask_file=None, no_points=1000,
                xlabel='nii1', ylabel='nii2', title='title'):
    nii = nib.load(nii_1)
    img_1 = nii.get_data()

    nii = nib.load(nii_2)
    img_2 = nii.get_data()

    if not(mask_file==None):
        nii = nib.load(mask_file)
        mask = nii.get_data()==0
    else:
        mask = img_1 != 0  # get the foreground voxels

    opt=[] # just a junk
    correlation_plot_and_analyse(img_1, img_2, mask, no_points=no_points,
                                 xlabel=xlabel, ylabel=ylabel, title=title, opt=opt)
    plt.show()


def scatter_plot_with_correlation_line(x, y, graph_filepath=None):
    # Scatter plot
    plt.scatter(x, y, color='g', alpha=0.05, marker='o')

    # Add correlation line
    axes = plt.gca()
    axes.set_xlim([0, np.max(x)])
    axes.set_ylim([0, np.max(y)])
    m, b = np.polyfit(x, y, 1)
    X_plot = np.linspace(np.min(x), np.max(x), 100)
    #X_plot = np.linspace(axes.get_xlim()[0],axes.get_xlim()[1],100)
    plt.plot(X_plot, m*X_plot + b, '-', color='r')


    # Save figure
    if not(graph_filepath==None):
        plt.savefig(graph_filepath,
                    dpi=300, format='png', bbox_inches='tight')


def compare_images(img_gt, img_est, mask):
    """Compute RMSE, PSNR, MSSIM:
     img_gt: (4D numpy array with the last dim being channels)
     ground truth volume
     img_est: (4D numpy array) predicted volume
     mask: (3D array) the mask whose the tissue voxles
     are labelled as 1 and the rest as 0
     """
    m = compute_rmse(img_gt,img_est,mask)
    p = compute_psnr(img_gt, img_est, mask)
    s = compute_mssim(img_gt,img_est,mask)
    # print("RMSE: %.10f \nPSNR: %.6f \nSSIM: %.6f" % (m,p,s))
    return m,p,s

def compute_rmse(img1, img2, mask):
    if img1.shape != img2.shape:
        print("shape of img1 and img2: %s and %s" % (img1.shape, img2.shape))
        raise ValueError("the size of img 1 and img 2 do not match")

    mse = np.sum(((img1-img2)**2)*mask[...,np.newaxis]) \
          /(mask.sum()*img1.shape[-1])
    return np.sqrt(mse)

def compute_mssim(img1, img2, mask):
    if img1.shape != img2.shape:
        print("shape of img1 and img2: %s and %s" % (img1.shape, img2.shape))
        raise ValueError("the size of img 1 and img 2 do not match")
    img1=img1*mask[...,np.newaxis]
    img2=img2*mask[...,np.newaxis]

    m, S = ssim(img1,img2,
                dynamic_range=np.max(img1)-np.min(img1[mask]),
                gaussian_weights=True,
                sigma=1.5,
                use_sample_covariance=False,
                full=True,
                multichannel=True)

    mssim = np.sum(S * mask[..., np.newaxis]) / (mask.sum() * img1.shape[-1])

    return mssim


def compute_psnr(img1, img2, mask):
    """ Compute PSNR
    Arg:
        img1: ground truth image
        img2: test image
    """
    if img1.shape != img2.shape:
        print("shape of img1 and img2: %s and %s" % (img1.shape, img2.shape))
        raise ValueError("the size of img 1 and img 2 do not match")
    img1 = img1 * mask[..., np.newaxis]
    img2 = img2 * mask[..., np.newaxis]

    true_min, true_max = np.min(img1[mask]), np.max(img1)

    if true_min >= 0:
        # most common case (255 for uint8, 1 for float)
        dynamic_range = true_max
    else:
        dynamic_range = true_max - true_min

    rmse = compute_rmse(img1, img2, mask)
    return 10 * np.log10((dynamic_range ** 2) / (rmse**2))

# Plot receiver operating chracteristics:
def plot_ROC(img_gt, img_est, img_std, mask, acceptable_err=1e-6, no_points=10000):
    """ Plot ROC with AUC computed.
    Args:
    """
    if img_gt.shape != img_est.shape:
        print("shape of img_gt and img_est: %s and %s" % (img_gt.shape, img_est.shape))

    # Compute true positive and false alarm rates:
    img_err = np.sqrt((img_gt-img_est)**2)*mask
    img_std = img_std*mask
    tp, fp = compute_tr_and_fp(img_err, img_std, mask, acceptable_err, no_points)

    # plot
    auc = np.trapz(tp, fp)
    plt.plot(fp, tp, 'b', label='AUC = %0.3f' % auc)
    plt.legend(loc='lower right')
    plt.plot([0, 1], [0, 1], 'r--')
    plt.xlim([0, 1])
    plt.ylim([0, 1])
    plt.ylabel('True Positive Rate')
    plt.xlabel('False Positive Rate')


def compute_tr_and_fp(img_err, img_std, mask, acceptable_err, no_points=10000):
    # subsample on the number of voxels
    brain_ind = [(i, j, k) for i in xrange(mask.shape[0])
                           for j in xrange(mask.shape[1])
                           for k in xrange(mask.shape[2])
                           if mask[i, j, k] == True]

    ind_sub = random.sample(brain_ind, no_points)
    err_subset, std_subset = np.zeros((no_points,)), np.zeros((no_points,))
    for idx, (i, j, k) in enumerate(ind_sub):
        err_subset[idx], std_subset[idx] = img_err[i, j, k], img_std[i, j, k]

    # prepare the labels and prediction:
    v_good = err_subset<acceptable_err  # labels = 1 if RMSE < acceptable_err
    v_bad = -v_good+1
    thresh = np.linspace(np.min(std_subset),np.max(std_subset),1000)

    # Compute true positive and false positive rates
    tp, fp = np.zeros(thresh.shape),np.zeros(thresh.shape)
    for idx,t in enumerate(thresh):
        v_good_guess=std_subset<t
        v_bad_guess=-v_good_guess+1
        tp[idx]=np.sum(v_good_guess*v_good)/np.sum(v_good)
        fp[idx]=np.sum(v_good_guess*v_bad)/np.sum(v_bad)
    return tp, fp








