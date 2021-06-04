import torch
import torch.nn as nn


def mse_loss(reconstructed_x, x, use_sum):
    if use_sum:
        return nn.functional.mse_loss(reconstructed_x, x, reduction="sum")
    else:
        return nn.functional.mse_loss(reconstructed_x, x, reduction="mean")


def kl_divergence(mu, log_var, use_sum):
    # Assumes a standard normal distribution for the 2nd gaussian
    inner_element = 1 + log_var - mu.pow(2) - log_var.exp()
    if use_sum:
        return -0.5 * torch.sum(inner_element)
    else:
        return -0.5 * torch.sum(inner_element, dim=1).mean()


def kl_divergence_two_gaussians(mu1, log_var1, mu2, log_var2, use_sum):
    # https://stats.stackexchange.com/questions/7440/kl-divergence-between-two-univariate-gaussians
    # Verify by setting mu2=torch.zeros((shape)), log_var2=torch.zeros((shape))
    # We use 0s for logvar since log 1 = 0.
    term1 = log_var1 - log_var2
    term2 = (log_var1.exp() + (mu1 - mu2).pow(2)) / log_var2.exp()
    if use_sum:
        kl_d = -0.5 * torch.sum(term1 - term2 + 1)
    else:
        kl_d = -0.5 * torch.sum(term1 - term2 + 1, dim=1).mean()
    return kl_d, {"KL Divergence": kl_d.item()}


def mse_ssim_loss(
    reconstructed_x, x, use_sum, ssim_module=None, mse_weight=1, ssim_weight=1
):
    mse = mse_weight * mse_loss(reconstructed_x, x, use_sum)
    if ssim_module:
        # ssim gives a score from 0-1 where 1 is the highest.
        # So we do 1 - ssim in order to minimize it.
        ssim = ssim_weight * (1 - ssim_module(reconstructed_x, x))
    else:
        ssim = torch.tensor(0)
    return mse + ssim, {"MSE": mse.item(), "SSIM": ssim.item()}


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
    mse_ssim, loss_dict = mse_ssim_loss(
        reconstructed_x,
        x,
        use_sum,
        ssim_module=ssim_module,
        mse_weight=mse_weight,
        ssim_weight=ssim_weight,
    )
    KL_d = kl_divergence(mu, log_var, use_sum)
    weighted_loss = (reconstruction_weight * mse_ssim) + (kl_weight * KL_d)
    return weighted_loss, {
        "MSE": loss_dict["MSE"],
        "SSIM": loss_dict["SSIM"],
        "KL Divergence": KL_d.item(),
    }
