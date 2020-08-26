import argparse
import os
import numpy as np
import math

import torchvision.transforms as transforms
from torchvision.utils import save_image
from PIL import Image

from torch.utils.data import DataLoader
from torchvision import datasets
from torch.autograd import Variable

from cv.GANs.PyTorch_GANs.ccgan.datasets import *
from cv.GANs.PyTorch_GANs.ccgan.models import *

import torch.nn as nn
import torch.nn.functional as F
import torch

os.makedirs("images", exist_ok=True)

parser = argparse.ArgumentParser()
parser.add_argument("--n_epochs", type=int, default=200, help="number of epochs of training")
parser.add_argument("--batch_size", type=int, default=8, help="size of the batches")
parser.add_argument("--dataset_name", type=str, default="img_align_celeba", help="name of the dataset")
parser.add_argument("--lr", type=float, default=0.0002, help="adam: learning rate")
parser.add_argument("--b1", type=float, default=0.5, help="adam: decay of first order momentum of gradient")
parser.add_argument("--b2", type=float, default=0.999, help="adam: decay of first order momentum of gradient")
parser.add_argument("--n_cpu", type=int, default=8, help="number of cpu threads to use during batch generation")
parser.add_argument("--latent_dim", type=int, default=100, help="dimensionality of the latent space")
parser.add_argument("--img_size", type=int, default=128, help="size of each image dimension")
parser.add_argument("--mask_size", type=int, default=32, help="size of random mask")
parser.add_argument("--channels", type=int, default=3, help="number of image channels")
parser.add_argument("--sample_interval", type=int, default=500, help="interval between image sampling")
opt = parser.parse_args()
print(opt)

def weights_init_normal(m):
    classname = m.__class__.__name__
    if classname.find("Conv") != -1:
        torch.nn.init.normal_(m.weight.data, 0.0, 0.02)
    elif classname.find("BatchNorm2d") != -1:
        torch.nn.init.normal_(m.weight.data, 1.0, 0.02)
        torch.nn.init.constant_(m.bias.data, 0.0)

def apply_random_mask(imgs,img_size,mask_size):
    idx = np.random.randint(0, img_size - mask_size, (imgs.shape[0], 2))

    masked_imgs = imgs.clone()
    for i, (y1, x1) in enumerate(idx):
        y2, x2 = y1 + mask_size, x1 + mask_size
        masked_imgs[i, :, y1:y2, x1:x2] = -1

    return masked_imgs


class CCGAN():
    def __init__(self,lr = 0.0002,b1 = 0.5, b2 = 0.999, latent_dim = 100,img_size = 128,channels = 3):
        self.input_shape = (channels, img_size, img_size)
        self.lr = lr
        self.b1 = b1
        self.b2 = b2
        self.latent_dim = latent_dim
        self.img_size = img_size
        self.channels = channels
      
        # Loss function
        self.adversarial_loss = torch.nn.MSELoss()

        # Initialize generator and discriminator
        self.generator = Generator(self.input_shape)
        self.discriminator = Discriminator(self.input_shape)

        cuda = False #True if torch.cuda.is_available() else False
        if cuda:
            self.generator.cuda()
            self.discriminator.cuda()
            self.adversarial_loss.cuda()

        # Initialize weights
        self.generator.apply(weights_init_normal)
        self.discriminator.apply(weights_init_normal)



        # Optimizers
        self.optimizer_G = torch.optim.Adam(self.generator.parameters(), lr=self.lr, betas=(self.b1, self.b2))
        self.optimizer_D = torch.optim.Adam(self.discriminator.parameters(), lr=self.lr, betas=(self.b1, self.b2))

        self.Tensor = torch.cuda.FloatTensor if cuda else torch.FloatTensor


    def save_sample(self,saved_samples,batches_done):
        # Generate inpainted image
        gen_imgs = self.generator(saved_samples["masked"], saved_samples["lowres"])
        # Save sample
        sample = torch.cat((saved_samples["masked"].data, gen_imgs.data, saved_samples["imgs"].data), -2)
        save_image(sample, "images/%d.png" % batches_done, nrow=5, normalize=True)


    def train(self,n_epochs,mask_size):
        saved_samples = {}
        cuda = False #True if torch.cuda.is_available() else False
        for epoch in range(opt.n_epochs):
            for i, batch in enumerate(dataloader):
                imgs = batch["x"]
                imgs_lr = batch["x_lr"]

                masked_imgs = apply_random_mask(imgs,self.img_size, mask_size)

                # Adversarial ground truths
                valid = Variable(self.Tensor(imgs.shape[0], *self.discriminator.output_shape).fill_(1.0), requires_grad=False)
                fake = Variable(self.Tensor(imgs.shape[0], *self.discriminator.output_shape).fill_(0.0), requires_grad=False)

                if cuda:
                    imgs = imgs.type(self.Tensor)
                    imgs_lr = imgs_lr.type(self.Tensor)
                    masked_imgs = masked_imgs.type(self.Tensor)

                real_imgs = Variable(imgs)
                imgs_lr = Variable(imgs_lr)
                masked_imgs = Variable(masked_imgs)

                # -----------------
                #  Train Generator
                # -----------------

                self.optimizer_G.zero_grad()

                # Generate a batch of images
                gen_imgs = self.generator(masked_imgs, imgs_lr)

                # Loss measures generator's ability to fool the discriminator
                g_loss = self.adversarial_loss(self.discriminator(gen_imgs), valid)

                g_loss.backward()
                self.optimizer_G.step()

                # ---------------------
                #  Train Discriminator
                # ---------------------

                self.optimizer_D.zero_grad()

                # Measure discriminator's ability to classify real from generated samples
                real_loss = self.adversarial_loss(self.discriminator(real_imgs), valid)
                fake_loss = self.adversarial_loss(self.discriminator(gen_imgs.detach()), fake)
                d_loss = 0.5 * (real_loss + fake_loss)

                d_loss.backward()
                self.optimizer_D.step()

                print(
                    "[Epoch %d/%d] [Batch %d/%d] [D loss: %f] [G loss: %f]"
                    % (epoch, opt.n_epochs, i, len(dataloader), d_loss.item(), g_loss.item())
                )

                # Save first ten samples
                if not saved_samples:
                    saved_samples["imgs"] = real_imgs[:1].clone()
                    saved_samples["masked"] = masked_imgs[:1].clone()
                    saved_samples["lowres"] = imgs_lr[:1].clone()
                elif saved_samples["imgs"].size(0) < 10:
                    saved_samples["imgs"] = torch.cat((saved_samples["imgs"], real_imgs[:1]), 0)
                    saved_samples["masked"] = torch.cat((saved_samples["masked"], masked_imgs[:1]), 0)
                    saved_samples["lowres"] = torch.cat((saved_samples["lowres"], imgs_lr[:1]), 0)

                batches_done = epoch * len(dataloader) + i
                if batches_done % opt.sample_interval == 0:
                    self.save_sample(saved_samples,batches_done)





'''

# Dataset loader
transforms_ = [
    transforms.Resize((opt.img_size, opt.img_size), Image.BICUBIC),
    transforms.ToTensor(),
    transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
]
transforms_lr = [
    transforms.Resize((opt.img_size // 4, opt.img_size // 4), Image.BICUBIC),
    transforms.ToTensor(),
    transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
]
dataloader = DataLoader(
    ImageDataset("../../data/%s" % opt.dataset_name, transforms_x=transforms_, transforms_lr=transforms_lr),
    batch_size=opt.batch_size,
    shuffle=True,
    num_workers=opt.n_cpu,
)'''
