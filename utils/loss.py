import torch
import torch.nn as nn


def mse_loss(reconstructed_x, x, use_sum):
    if use_sum:
        return nn.functional.mse_loss(reconstructed_x, x, reduction="sum")
    else:
        return nn.functional.mse_loss(reconstructed_x, x, reduction="mean")


def kl_divergence(mu, log_var, use_sum):
    if use_sum:
        return -0.5 * torch.sum(1 + log_var - mu.pow(2) - log_var.exp())
    else:
        return -0.5 * torch.mean(1 + log_var - mu.pow(2) - log_var.exp())


def VAE_loss(
    reconstructed_x,
    x,
    mu,
    log_var,
    use_sum=True,
    ssim_module=None,
    mse_weight=1,
    ssim_weight=1,
    reconstruction_weight=1,
    kl_weight=1,
):
    mse = mse_loss(reconstructed_x, x, use_sum)
    if ssim_module:
        # ssim gives a score from 0-1 where 1 is the highest.
        # So we do 1 - ssim in order to minimize it.
        ssim = 1 - ssim_module(reconstructed_x, x)
    else:
        ssim = 0
    KL_d = kl_divergence(mu, log_var, use_sum)
    weighted_reconstruction = (mse_weight + mse) + (ssim_weight + ssim)
    weighted_loss = (reconstruction_weight * weighted_reconstruction) + (
        kl_weight * KL_d
    )
    return weighted_loss, (mse, ssim, KL_d)