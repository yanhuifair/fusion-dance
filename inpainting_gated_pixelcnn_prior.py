import os

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
import pytorch_msssim
from tqdm import tqdm

import utils.data as data
import utils.graphics as graphics
import utils.loss as loss
from models import vqvae, gated_pixelcnn

seed = 42
np.random.seed(seed)
_ = torch.manual_seed(seed)

################################################################################
#################################### Config ####################################
################################################################################
learning_rate = 1e-4
epochs = 25
batch_size = 32
num_dataloader_workers = 0
image_size = 64

experiment_name = f"inpainting_pixelcnn_v1"

# VQ-VAE Config
mode = "discrete"
vq_vae_experiment_name = f"vq_vae_v5.8"
vq_vae_num_layers = 1
vq_vae_max_filters = 512
vq_vae_use_max_filters = True
vq_vae_num_embeddings = 256
vq_vae_embedding_dim = 32
vq_vae_commitment_cost = 0.25
vq_vae_small_conv = True  # To use the 1x1 convolution layer

# Pixel CNN Config
input_dim = image_size // (2 ** vq_vae_num_layers)
input_channels = 1
hidden_channels = 128
num_classes = vq_vae_num_embeddings
kernel_size = 3
sample_batch_size = batch_size
num_sample_batches = 5
use_bits_per_dimension_loss = False
use_dilation = True
use_modified_model = True

# Data Config
data_prefix = "data\\pokemon\\inpainting"
output_prefix = f"data\\{experiment_name}"
vq_vae_model_prefix = f"outputs\\{vq_vae_experiment_name}"
vq_vae_model_path = os.path.join(vq_vae_model_prefix, "model.pt")

train_dir = os.path.join(data_prefix, "train")
val_dir = os.path.join(data_prefix, "val")
test_dir = os.path.join(data_prefix, "test")

output_dir = os.path.join(output_prefix, "generated")
recon_output_dir = os.path.join(output_prefix, "reconstructed")
loss_output_path = output_prefix
model_output_path = os.path.join(output_prefix, "model.pt")
################################################################################
##################################### Setup ####################################
################################################################################

# Setup Device
gpu = torch.cuda.is_available()
device = torch.device("cuda" if gpu else "cpu")
print(gpu, device)

# Create Output Paths
if not os.path.exists(output_dir):
    os.makedirs(output_dir)
if not os.path.exists(recon_output_dir):
    os.makedirs(recon_output_dir)

################################################################################
################################## Data Setup ##################################
################################################################################

# Preprocess & Create Data Loaders
transform = data.image2tensor_resize(image_size)

train_data = data.InpaintingDataset(train_dir, transform)
val_data = data.InpaintingDataset(val_dir, transform)
test_data = data.InpaintingDataset(test_dir, transform)

train_dataloader = torch.utils.data.DataLoader(
    train_data,
    batch_size=batch_size,
    shuffle=True,
    num_workers=num_dataloader_workers,
    pin_memory=gpu,
)
val_dataloader = torch.utils.data.DataLoader(
    val_data,
    batch_size=batch_size,
    shuffle=True,
    num_workers=num_dataloader_workers,
    pin_memory=gpu,
)
test_dataloader = torch.utils.data.DataLoader(
    test_data,
    batch_size=batch_size,
    shuffle=True,
    num_workers=num_dataloader_workers,
    pin_memory=gpu,
)
# Creating a sample set to visualize the model's training
sample = data.get_samples_from_data(val_data, 16)

################################################################################
##################################### Model ####################################
################################################################################

# Create & Load VQVAE Model
vq_vae = vqvae.VQVAE(
    num_layers=vq_vae_num_layers,
    input_image_dimensions=image_size,
    small_conv=vq_vae_small_conv,
    embedding_dim=vq_vae_embedding_dim,
    num_embeddings=vq_vae_num_embeddings,
    commitment_cost=vq_vae_commitment_cost,
    use_max_filters=vq_vae_use_max_filters,
    max_filters=vq_vae_max_filters,
)
vq_vae.load_state_dict(torch.load(vq_vae_model_path, map_location=device))
vq_vae.eval()
vq_vae.to(device)

# Create Model
if use_modified_model:
    model = gated_pixelcnn.InpaintingPixelCNN(
        c_in=input_channels,
        c_hidden=hidden_channels,
        num_classes=num_classes,
        kernel_size=kernel_size,
        use_dilation=use_dilation,
    )
else:
    model = gated_pixelcnn.PixelCNN(
        c_in=input_channels,
        c_hidden=hidden_channels,
        num_classes=num_classes,
        kernel_size=kernel_size,
        use_dilation=use_dilation,
    )
model.to(device)
print(model)

optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
if use_bits_per_dimension_loss:
    criterion = loss.bits_per_dimension_loss
else:
    criterion = nn.CrossEntropyLoss()

################################################################################
################################### Training ###################################
################################################################################

# Train
all_train_loss = []
all_val_loss = []

for epoch in range(epochs):
    train_loss = 0
    val_loss = 0

    # Training Loop
    model.train()
    for iteration, batch in enumerate(tqdm(train_dataloader)):
        # Reset gradients back to zero for this iteration
        optimizer.zero_grad()

        # Move batch to device
        _, inputs, outputs = batch  # (names), (images)
        inputs = inputs.to(device)
        outputs = outputs.to(device)
        current_batch_size = inputs.shape[0]

        with torch.no_grad():
            # Get Encodings from vq_vae
            _, _, _, encodings = vq_vae(inputs)
            inputs = encodings.reshape(current_batch_size, 1, input_dim, input_dim)
            _, _, _, labels = vq_vae(outputs)
            labels = labels.reshape(current_batch_size, 1, input_dim, input_dim)

        # Run our model & get outputs
        y_hat = model.forward(inputs)
        batch_loss = criterion(y_hat, labels)

        # Backprop
        batch_loss.backward()

        # Update our optimizer parameters
        optimizer.step()

        # Add the batch's loss to the total loss for the epoch
        train_loss += batch_loss.item()

    # Validation Loop
    model.eval()
    with torch.no_grad():
        for iteration, batch in enumerate(tqdm(val_dataloader)):
            # Move batch to device
            _, inputs, outputs = batch  # (names), (images)
            inputs = inputs.to(device)
            outputs = outputs.to(device)
            current_batch_size = inputs.shape[0]

            # Get Encodings from vq_vae
            _, _, _, encodings = vq_vae(inputs)
            inputs = encodings.reshape(current_batch_size, 1, input_dim, input_dim)
            _, _, _, labels = vq_vae(outputs)
            labels = labels.reshape(current_batch_size, 1, input_dim, input_dim)

            # Run our model & get outputs
            y_hat = model.forward(inputs)
            batch_loss = criterion(y_hat, labels)

            # Add the batch's loss to the total loss for the epoch
            val_loss += batch_loss.item()

    # Compute the average losses for this epoch
    train_loss = train_loss / len(train_dataloader)
    all_train_loss.append(train_loss)

    val_loss = val_loss / len(val_dataloader)
    all_val_loss.append(val_loss)

    # Print Metrics
    print(
        f"\nEpoch: {epoch+1}/{epochs}:\
        \nTrain Loss = {train_loss}\
        \nVal Loss = {val_loss}"
    )

################################################################################
################################## Save & Test #################################
################################################################################
# Generate Loss Graph
graphics.draw_loss(all_train_loss, all_val_loss, loss_output_path, mode="autoencoder")

# Save Model
torch.save(
    {
        "epoch": epoch,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "train_loss": all_train_loss,
        "val_loss": all_val_loss,
    },
    model_output_path,
)

# Evaluation Time
model.eval()

# Compute bpd loss on test images
test_loss = 0
with torch.no_grad():
    for iteration, batch in enumerate(tqdm(test_dataloader)):
        # Move batch to device
        filenames, inputs, outputs = batch  # (names), (images)
        inputs = inputs.to(device)
        outputs = outputs.to(device)
        current_batch_size = inputs.shape[0]

        # Get Encodings from vq_vae
        _, _, _, encodings = vq_vae(inputs)
        inputs = encodings.reshape(current_batch_size, 1, input_dim, input_dim)
        _, _, _, labels = vq_vae(outputs)
        labels = labels.reshape(current_batch_size, 1, input_dim, input_dim)

        # Run our model & get outputs
        y_hat = model.forward(inputs)
        batch_loss = criterion(y_hat, labels)

        # Add the batch's loss to the total loss for the epoch
        test_loss += batch_loss.item()

        # Save to disk
        target_shape = (
            y_hat.shape[0],
            input_dim,
            input_dim,
            vq_vae_embedding_dim,
        )
        y_hat = y_hat.argmax(dim=1).flatten(start_dim=1).view(-1, 1)
        y_hat = vq_vae.quantize_and_decode(y_hat, target_shape, device)
        y_hat = y_hat.permute(0, 2, 3, 1).detach().cpu().numpy()
        for image, filename in zip(y_hat, filenames):
            plt.imsave(os.path.join(recon_output_dir, filename), image)

test_loss = test_loss / len(test_dataloader)
print(f"Test Loss: {test_loss}")

# Generate samples
target_shape = (sample_batch_size, input_dim, input_dim, vq_vae_embedding_dim)
image_shape = (sample_batch_size, input_channels, input_dim, input_dim)
for i in range(num_sample_batches):
    # Sample from model
    sample = model.sample(image_shape, device)
    # Feed into VQ-VAE
    sample = sample.flatten(start_dim=1).view(-1, 1)
    sample = vq_vae.quantize_and_decode(sample, target_shape, device)
    # Convert to image
    sample = sample.permute(0, 2, 3, 1).detach().cpu().numpy()
    # Save
    for filename, image in enumerate(sample):
        filename = f"{(i*sample_batch_size)+filename}.png"
        plt.imsave(os.path.join(output_dir, filename), image)
