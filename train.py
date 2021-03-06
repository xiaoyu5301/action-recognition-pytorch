import argparse
import os
import shutil

import torch
import torch.nn as nn
import torchvision.models as models
from torchvision import transforms, utils
from torch.autograd import Variable
import torch.nn.functional as F

import dataset
from lstm_arch import *

parser = argparse.ArgumentParser(description = 'Training')

# important parameter
parser.add_argument('data', metavar = 'DIR', help = 'path to dataset')
parser.add_argument('--model', default='', type=str, metavar = 'DIR', help = 'path to model')
parser.add_argument('--epochs', default=90, type=int, metavar='N', 
					help='manual epoch number' + ' (default: 90)')
parser.add_argument('--lr', default=0.01, type=float,
                    metavar='LR', help='initial learning rate' + ' (default: 0.01)')
parser.add_argument('--optim', default='rmsprop',type=str,
					help='optimizer' + ' (default: rmsprop)')

# parameters for sgd
parser.add_argument('--momentum', default=0.9, type=float, metavar='M',
                    help='momentum' + ' (default: 0.9)')
parser.add_argument('--lr_step', default=30, type=float,
					help='learning rate decay frequency' + ' (default: 30)')

# optional parameters
parser.add_argument('--arch', metavar = 'ARCH', default = 'alexnet', 
					help = 'model architecture' + ' (default: alexnet)')
parser.add_argument('--workers', default=8, type=int, metavar='N',
                    help='number of data loading workers (default: 8)')
parser.add_argument('--batch-size', default=1, type=int,
                    metavar='N', help='mini-batch size' + ' (default: 1)')
parser.add_argument('--weight-decay', default=1e-4, type=float,
                    metavar='W', help='weight decay (default: 1e-4)')
parser.add_argument('--lstm-layers', default=1, type=int, metavar='LSTM',
					help='number of lstm layers' + ' (default: 1)')
parser.add_argument('--hidden-size', default=512, type=int, metavar='HIDDEN',
					help='output size of LSTM hidden layers' + ' (default: 512)')
parser.add_argument('--fc-size', default=1024, type=int,
					help='size of fully connected layer before LSTM' + ' (default: 1024)')

def train(train_loader, model, criterion, optimizer, epoch):
	losses = AverageMeter()

	model.train()	# switch to train mode

	for i, (input, target) in enumerate(train_loader):

		# wrap inputs and targets in Variable
		input_var = torch.autograd.Variable(input)
		target_var = torch.autograd.Variable(target)

		input_var, target_var = input_var.cuda(), target_var.cuda()
		# compute output
		output, _ = model(input_var[0])
		# output = output.unsqueeze(0)
		target_var = target_var.repeat(output.shape[0])
		loss_t = criterion(output, target_var)
		weight = Variable(torch.Tensor(range(output.shape[0])) / (output.shape[0] - 1)).cuda()
		loss = torch.mean(loss_t * weight)
		losses.update(loss.item(), input.size(0))

		# zero the parameter gradients
		optimizer.zero_grad()
		# compute gradient
		loss.backward()
		optimizer.step()
		
		if i % 10 == 0:
			print('Epoch: [{0}][{1}/{2}]\t'
				'lr {lr:.5f}\t'
				'Loss {loss.val:.4f} ({loss.avg:.4f})\t'.format(
				epoch, i, len(train_loader), lr=optimizer.param_groups[-1]['lr'],
				loss=losses))


def validate(val_loader, model, criterion):
	losses = AverageMeter()
	top = AverageMeter()

	# switch to evaluate mode
	model.eval()

	for i, (input, target) in enumerate(val_loader):

		# target = target.cuda(async=True)
		input_var = torch.autograd.Variable(input)
		target_var = torch.autograd.Variable(target)

		input_var, target_var = input_var.cuda(), target_var.cuda()

		# compute output
		output, _ = model(input_var[0])
		weight = Variable(torch.Tensor(range(output.shape[0])) / (output.shape[0] - 1)).cuda()
		output = torch.sum(output * weight.unsqueeze(1), dim=0, keepdim=True)
		loss = criterion(output, target_var)

		# measure accuracy and record loss
		prec = accuracy(output.data.cpu(), target)
		losses.update(loss.item(), input.size(0))
		top.update(prec[0], input.size(0))

		if i % 10 == 0:
			print ('Test: [{0}/{1}]\t'
					'Loss {loss.val:.4f} ({loss.avg:.4f})\t'.format(
					i, len(val_loader), loss=losses
					))

	return top.avg


def save_checkpoint(state, is_best, filename='checkpoint.pth.tar'):
    torch.save(state, './data/save_model/' + filename)
    if is_best:
        shutil.copyfile('./data/save_model/' + filename, './data/save_model/model_best.pth.tar')

class AverageMeter(object):
	def __init__(self):
		self.reset()

	def reset(self):
		self.val = 0
		self.avg = 0
		self.sum = 0
		self.count = 0

	def update(self, val, n=1):
		self.val = val
		self.sum += val * n
		self.count += n
		self.avg = self.sum / self.count


def adjust_learning_rate(optimizer, epoch):
    if not epoch % args.lr_step and epoch:
    	for param_group in optimizer.param_groups:
    		param_group['lr'] = param_group['lr'] * 0.1
    return optimizer


def accuracy(output, target, topk=(1,)):
    maxk = max(topk)
    batch_size = target.size(0)

    _, pred = output.topk(maxk, 1, True, True)
    pred = pred.t()
    correct = pred.eq(target.view(1, -1).expand_as(pred))

    res = []
    for k in topk:
        correct_k = correct[:k].view(-1).float().sum(0, keepdim=True)
        res.append(correct_k.mul_(100.0 / batch_size))
    return res



def main():
	global args

	best_prec = 0
	args = parser.parse_args()

	# Data Transform and data loading
	traindir = os.path.join(args.data, 'train_data')
	valdir = os.path.join(args.data, 'valid_data')

	normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
									std=[0.339, 0.224, 0.225])

	transform = (transforms.Compose([
									transforms.Resize(224),
									transforms.CenterCrop(224),
									transforms.ToTensor(),
									normalize]
									),
				transforms.Compose([
									transforms.Resize(224),
									transforms.CenterCrop(224),
									transforms.ToTensor()]
									)
				)

	train_dataset = dataset.CLMarshallingDataset(traindir, transform)

	train_loader = torch.utils.data.DataLoader(train_dataset, 
		batch_size=args.batch_size, shuffle=True,
		num_workers=args.workers, pin_memory=True)

	val_loader = torch.utils.data.DataLoader(
		dataset.CLMarshallingDataset(valdir, transform),
		batch_size=args.batch_size, shuffle=False,
		num_workers=args.workers, pin_memory=True)

	if os.path.exists(args.model):
		# load existing model
		model_info = torch.load(args.model)
		print("==> loading existing model '{}' ".format(model_info['arch']))
		original_model = models.__dict__[model_info['arch']](pretrained=False)
		model = FineTuneLstmModel(original_model, model_info['arch'],
			model_info['num_classes'], model_info['lstm_layers'], model_info['hidden_size'], model_info['fc_size'])
		print(model)
		model.cuda()
		model.load_state_dict(model_info['state_dict'])
	else:
		# load and create model
		print("==> creating model '{}' ".format(args.arch))

		original_model = models.__dict__[args.arch](pretrained=True)	
		model = FineTuneLstmModel(original_model, args.arch, 
			len(train_dataset.classes), args.lstm_layers, args.hidden_size, args.fc_size)
		print(model)
		model.cuda()

	# loss criterion and optimizer
	criterion = nn.CrossEntropyLoss(reduction='none')
	criterion = criterion.cuda()

	if args.optim == 'sgd':
		optimizer = torch.optim.SGD([{'params': model.features.parameters(), 'lr': args.lr}, 
									{'params': model.fc_pre.parameters()}, 
									{'params': model.rnn.parameters()}, {'params': model.fc.parameters()}],
									lr=args.lr, momentum=args.momentum, weight_decay=args.weight_decay)
	elif args.optim == 'adam':
		optimizer = torch.optim.Adam([{'params': model.features.parameters(), 'lr': args.lr}, 
									{'params': model.fc_pre.parameters()}, 
									{'params': model.rnn.parameters()}, {'params': model.fc.parameters()}],
									lr=args.lr, weight_decay=args.weight_decay)

	elif args.optim == 'rmsprop':
		optimizer = torch.optim.RMSprop([{'params': model.features.parameters(), 'lr': args.lr}, 
									{'params': model.fc_pre.parameters()}, 
									{'params': model.rnn.parameters()}, {'params': model.fc.parameters()}],
									lr=args.lr, weight_decay=args.weight_decay)

	# Training on epochs
	for epoch in range(args.epochs):
		
		if args.optim == 'sgd':
			optimizer = adjust_learning_rate(optimizer, epoch)

		# train on one epoch
		train(train_loader, model, criterion, optimizer, epoch)

		# evaluate on validation set
		prec = validate(val_loader, model, criterion)

		# remember best prec@1 and save checkpoint
		is_best = prec > best_prec
		best_prec = max(prec, best_prec)
		save_checkpoint({
			'epoch': epoch + 1,
			'arch': args.arch,
			'num_classes': len(train_dataset.classes),
			'lstm_layers': args.lstm_layers,
			'hidden_size': args.hidden_size,
			'fc_size': args.fc_size,
			'state_dict': model.state_dict(),
			'best_prec': best_prec,
			'optimizer' : optimizer.state_dict(),}, is_best)
		
if __name__ == '__main__':
	main()
