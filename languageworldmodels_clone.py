# -*- coding: utf-8 -*-
"""LanguageWorldModels_clone.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/13xQL3KFcmDnkjaOkc066Yq-7TeQkdDJk

# Step1
既存の論文（[Emergent Communication with World Models](https://arxiv.org/abs/2002.09604)）の実装を再現する。

## 1 準備
"""

# Commented out IPython magic to ensure Python compatibility.
# ライブラリのインポート
import torch
import torch.nn as nn
import torch.optim as optim
from torch.distributions import Categorical, Gumbel
import torch.nn.functional as F
from torchvision import datasets, transforms
from torch.utils.tensorboard import SummaryWriter
from copy import deepcopy
from tqdm import tqdm
import random
import math
import numpy as np
import matplotlib.pyplot as plt
# %matplotlib inline
# 可視化のためにTensorBoardを用いるので, Colab上でTensorBoardを表示するための宣言を行う
# %load_ext tensorboard

# torch.deviceを定義
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(device)

"""## 2 環境
今回使う二次元迷路の環境を準備する。

環境は上の図のようなものである。**話し手（画面外）**はマップ全体を見ることができるが、**聞き手（青）**は各方向のピクセルしか見ることができない。各ゲームの開始時に、**旗（緑）**が2つの経路のうちの1つにランダムに配置される。聞き手が正しい通路を選んで旗を見つけることができれば、話し手と聞き手の両方が報酬を受け取ることができる。とりあえず、左をグリッドA、右をグリッドBとし、9×9で実装する。
"""

class State():

    def __init__(self, row=-1, column=-1):
        self.row = row
        self.column = column

    def __repr__(self):
        return "<State: [{}, {}]>".format(self.row, self.column)

    def clone(self):
        return State(self.row, self.column)

    def __hash__(self):
        return hash((self.row, self.column))

    def __eq__(self, other):
        return self.row == other.row and self.column == other.column

class Environment():

    def __init__(self, grid_type='A', move_prob=1.0):

        # Make a grid environment.
        self.grid_type = grid_type

        # grid is 2d-array. Its values are treated as an attribute.
        # Kinds of attribute is following.
        #  0: ordinary cell
        #  -1: damage cell (game end)
        #  1: reward cell (game end)
        #  9: block cell (can't locate agent)

        if self.grid_type=='A':
            # Environment A

            init_grid = [
                [9, 9, 9, 9, 9, 9, 9, 9, 9],
                [9, 0, 0, 0, 0, 0, 0, 0, 9],
                [9, 0, 9, 9, 9, 9, 9, 9, 9],
                [9, 0, 9, 9, 9, 9, 9, 9, 9],
                [9, 0, 0, 0, 0, 0, 0, 0, 9],
                [9, 0, 9, 9, 9, 9, 9, 9, 9],
                [9, 0, 9, 9, 9, 9, 9, 9, 9],
                [9, 0, 0, 0, 0, 0, 0, 0, 9],
                [9, 9, 9, 9, 9, 9, 9, 9, 9],
            ]

            # start pos = [4][7]
            start_row, start_col = 4, 7

        elif self.grid_type=='B':
            # Environment B

            init_grid = [
                [9, 9, 9, 9, 9, 9, 9, 9, 9],
                [9, 0, 0, 0, 0, 0, 0, 0, 9],
                [9, 0, 9, 0, 9, 9, 9, 9, 9],
                [9, 0, 9, 0, 9, 0, 0, 0, 9],
                [9, 0, 9, 0, 9, 0, 0, 0, 9],
                [9, 0, 9, 0, 9, 0, 0, 0, 9],
                [9, 0, 9, 0, 9, 0, 0, 0, 9],
                [9, 0, 9, 0, 9, 0, 0, 0, 9],
                [9, 9, 9, 9, 9, 9, 9, 9, 9],
            ]

            # start pos = [1][7]
            start_row, start_col = 1, 7

        else:
            raise Exception("'grid_type' must be 'A' or 'B'!")

        self.init_grid = init_grid # reward cellの位置が指定されていない（reward cellの位置はepospdeごとに変えたいので、self.reset()内で指定）
        self.init_state = State(row=start_row, column=start_col)

        self.reset()

        # Default reward is minus. Just like a poison swamp.
        # It means the agent has to reach the goal fast!
        self.default_reward = -0.04

        # Agent can move to a selected direction in move_prob.
        # It means the agent will move different direction
        # in (1 - move_prob).
        self.move_prob = move_prob

    def reset(self):
        # Locate the agent at init_state.
        self.state = self.init_state.clone()

        # Reset grid
        self.grid = deepcopy(self.init_grid)
        # Decide position of reward cell randomly
        reward_pos = random.randint(0, 5)

        if self.grid_type=='A':
            # reward cell must be somewhere on one of the corridors
            reward_x = reward_pos % 3
            reward_y = reward_pos % 2
            if reward_y == 0:
                self.grid[1][reward_x*3+1] = 1
                #self.grid[1][3] = 1
            else:
                self.grid[-2][reward_x*3+1] = 1
                #self.grid[-2][3] = 1

        elif self.grid_type=='B':
            # reward cell must be somewhere on one of the corridors
            reward_x = reward_pos % 2
            reward_y = reward_pos % 3
            if reward_x == 0:
                self.grid[reward_y*3+1][3] = 1
            else:
                self.grid[reward_y*3+1][3] = 1

        return self.grid, self.state

    @property
    def row_length(self):
        return len(self.grid)

    @property
    def column_length(self):
        return len(self.grid[0])

    @property
    def actions(self):
        return [0, 1, 2, 3] # (UP, LEFT, DOWN, RIGHT)

    @property
    def states(self):
        states = []
        for row in range(self.row_length):
            for column in range(self.column_length):
                # Block cells are not included to the state.
                if self.grid[row][column] != 9:
                    states.append(State(row, column))
        return states

    def transit_func(self, state, action):
        transition_probs = {}
        if not self.can_action_at(state):
            # Already on the terminal cell.
            return transition_probs

        opposite_direction = (action + 2) % 4

        for a in self.actions:
            prob = 0
            if a == action:
                prob = self.move_prob
            elif a != opposite_direction:
                prob = (1 - self.move_prob) / 2

            next_state = self._move(state, a)
            if next_state not in transition_probs:
                transition_probs[next_state] = prob
            else:
                transition_probs[next_state] += prob

        return transition_probs

    def can_action_at(self, state):
        if self.grid[state.row][state.column] == 0:
            return True
        else:
            return False

    def _move(self, state, action):
        if not self.can_action_at(state):
            raise Exception("Can't move from here!")

        next_state = state.clone()

        # Execute an action (move).
        if action == 0: # UP
            next_state.row -= 1
        elif action == 2: # DOWN
            next_state.row += 1
        elif action == 1: # LEFT
            next_state.column -= 1
        elif action == 3: #RIGHT
            next_state.column += 1

        # Check whether a state is out of the grid.
        if not (0 <= next_state.row < self.row_length):
            next_state = state
        if not (0 <= next_state.column < self.column_length):
            next_state = state

        # Check whether the agent bumped a block cell.
        if self.grid[next_state.row][next_state.column] == 9:
            next_state = state

        return next_state

    def reward_func(self, state):
        reward = self.default_reward
        done = False

        # Check an attribute of next state.
        attribute = self.grid[state.row][state.column]
        if attribute == 1:
            # Get reward! and the game ends.
            reward = 1
            done = True
        elif attribute == -1:
            # Get damage! and the game ends.
            reward = -1
            done = True

        return reward, done

    def step(self, action):
        next_state, reward, done = self.transit(self.state, action)
        if next_state is not None:
            self.state = next_state

        return next_state, reward, done

    def transit(self, state, action):
        transition_probs = self.transit_func(state, action)
        if len(transition_probs) == 0:
            return None, None, True

        next_states = []
        probs = []
        for s in transition_probs:
            next_states.append(s)
            probs.append(transition_probs[s])
        next_state = np.random.choice(next_states, p=probs)
        reward, done = self.reward_func(next_state)
        return next_state, reward, done

    def observation(self, partial=True):
        '''
        観測を出力する関数
            state : 環境における聞き手の状態(State(row, column))
            partial : 聞き手の部分観測である場合はTrue、話し手の全体観測である場合はFalse
        '''
        grid = torch.tensor(self.grid)
        row = self.state.row
        col = self.state.column

        # positions of ordinary cell
        pos_ordinary = (grid == 0)
        pos_ordinary[row, col] = False
        # position of reward cell
        pos_reward = (grid == 1)
        # position of block cell
        pos_block = (grid == 9)

        # initalize image (shape = (3 (r,g,b), *grid.shape))
        grid_img = torch.zeros((*grid.shape, 3))

        # color
        grid_img[:,:,0] += pos_ordinary * 255 + pos_block * 112.5
        grid_img[:,:,1] += pos_ordinary * 255 + pos_reward * 225 + pos_block * 112.5
        grid_img[:,:,2] += pos_ordinary * 255 + pos_block * 112.5
        grid_img[row, col, 2] = 225

        if partial:
            mask = np.zeros((*grid.shape, 3))
            mask[row-1:row+2, col-1:col+2, :] = 1
            grid_img *= mask

        return (grid_img/ 255.0).float()

"""## 3 モデルの実装

### 3-1 聞き手（Listener）
[World Models](https://worldmodels.github.io/)と対応づけながらモデルを実装する。
1. VAE-Seq (V)
2. Latent Belief Network (M)
3. Controller (C)

#### 3-1-1 VAE-Seq (V)
聞き手の部分観測$o_{t}\in\mathbb{R}^N$を潜在変数$z_{t}\in\mathbb{R}^n$(ただし、n ≪ N)に圧縮する。  
アーキテクチャには簡単なCNNを用いる。
"""

# torch.log(0)によるnanを防ぐ
def torch_log(x):
    return torch.log(torch.clamp(x, min=1e-10))

# VAEモデルの実装
class VAE_Seq(nn.Module):
    def __init__(self, z_dim):
        super(VAE_Seq, self).__init__()
        # Encoder, xを入力にガウス分布のパラメータmu, sigmaを出力
        self.conv_enc1 = nn.Conv2d(3, 8, 3)
        self.conv_enc2 = nn.Conv2d(8, 16, 3)
        self.dense_encmean = nn.Linear(16*5*5, z_dim)
        self.dense_encvar = nn.Linear(16*5*5, z_dim)

        # Decoder, zを入力にベルヌーイ分布のパラメータlambdaを出力
        self.dense_dec = nn.Linear(z_dim, 16*5*5)
        self.conv_dec1 = nn.ConvTranspose2d(16, 8, 3)
        self.conv_dec2 = nn.ConvTranspose2d(8, 3, 3)
    
    def _encoder(self, x):
        x = F.relu(self.conv_enc1(x))
        x = F.relu(self.conv_enc2(x))
        x = x.view(-1, 16*5*5)
        mean = self.dense_encmean(x)
        std = F.softplus(self.dense_encvar(x))
        return mean, std
    
    def _sample_z(self, mean, std):
        # 再パラメータ化トリック
        epsilon = torch.randn(mean.shape).to(device)
        return mean + std * epsilon
 
    def _decoder(self, z):
        x = F.relu(self.dense_dec(z))
        x = x.view(-1, 16, 5, 5)
        x = F.relu(self.conv_dec1(x))
        # 出力が0~1になるようにsigmoid
        x = torch.sigmoid(self.conv_dec2(x))
        return x

    def forward(self, x):
        mean, std = self._encoder(x)
        z = self._sample_z(mean, std)
        x = self._decoder(z)
        return x, z

    def loss(self, x):
        mean, std = self._encoder(x)
        # KL loss(正則化項)の計算. mean, stdは (batch_size , z_dim)
        KL = -0.5 * torch.mean(torch.sum(1 + torch_log(std**2) - mean**2 - std**2, dim=1))
    
        z = self._sample_z(mean, std)
        y = self._decoder(z)

        x = x.view(-1, 3*9*9)
        y = y.view(-1, 3*9*9)

        # reconstruction loss(負の再構成誤差)の計算. x, yともに (batch_size , 3*9*9)
        reconstruction = torch.mean(torch.sum(x * torch_log(y) + (1 - x) * torch_log(1 - y), dim=1))
        
        return KL, -reconstruction

# Latent Belief Networkモデルの実装
class LBN(nn.Module):
    def __init__(self, T, z_dim, m_dim, beta_dim):
        '''
        T : 最大ステップ数
        '''
        super(LBN, self).__init__()
        self.T = T
        self.z_dim = z_dim
        self.sigma = torch.tensor([0.1])
        # Encoder, (z, m)を入力にガウス分布のパラメータmu, sigmaを出力
        self.dense_enc1 = nn.Linear(z_dim + m_dim, 1000)
        self.dense_enc2 = nn.Linear(1000, 1000)
        self.dense_encmean = nn.Linear(1000, beta_dim)
        self.dense_encvar = nn.Linear(1000, beta_dim)

        # Decoder, betaを入力に次の時刻のzを出力
        self.rnn = nn.LSTM(input_size = beta_dim,
                            hidden_size = 1000)
        self.dense_dec = nn.Linear(1000, z_dim)

        # loss計算のための記憶
        self.z_memory = []
        self.m_memory = []
        self.beta_memory = []
        self.t_memory = []

        self.m_dim = m_dim
        self.z_dim = z_dim
        self.beta_dim = beta_dim
    
    def _encoder(self, z, m):
        x = torch.cat([z, m], dim=1)
        x = F.relu(self.dense_enc1(x))
        x = F.relu(self.dense_enc2(x))
        mean = self.dense_encmean(x)
        std = F.softplus(self.dense_encvar(x))
        return mean, std
    
    def _sample_beta(self, mean, std):
        # 再パラメータ化トリック
        epsilon = torch.randn(mean.shape).to(device)
        return mean + std * epsilon
 
    def _decoder(self, beta):
        hidden_init = None
        output, (hidden, cell) = self.rnn(beta, hidden_init) # hidden_initは隠れ層Hと記憶層Cの初期値、Noneの場合は零行列となる
        output = F.relu(output.view(-1, 1000)) # (系列長) * 2000 に変換
        z_pred = self.dense_dec(output)

        return z_pred

    def forward(self, z, m, beta, t):
        if m == None:
            # t=0の時はmessageを受け取る
            # こうすることで、episodeはじめに必ずbetaが更新されるので、前episodeのbetaが引き継がれずに済む
            if t==0:
                raise Exception("first message must be recieved at t=0")
            # messageが送られてきていない場合、betaは更新されない
            beta = beta
            z_pred = None
        else:
            mean, std = self._encoder(z, m)
            beta = self._sample_beta(mean, std)
        
        # 記憶する
        self.z_memory.append(z)
        self.beta_memory.append(beta)
        if m != None:
            self.m_memory.append(m)
            self.t_memory.append(t)

        return beta

    def loss(self):
        '''
        z_memory : 時刻tにおけるzの記憶(t_done, z_dim) (t_done : エピソード終了時のt)
        m_memory : messageの記憶(messageを受けとった回数, m_dim)
        beta_memory : 時刻tにおけるbetaの記憶(t_done, m_dim)
        t_memory : messageが送られた時刻tの記憶(messageを受けとった回数)
        '''
        z_memory = torch.squeeze(torch.stack(self.z_memory))
        m_memory = torch.squeeze(torch.stack(self.m_memory)).view(-1, self.m_dim) # viewはm_memoryに格納されたmが1つのみである場合への対策
        beta_memory = torch.squeeze(torch.stack(self.beta_memory))
        t_recieved = torch.tensor(self.t_memory)

        # KL lossの計算. mean, stdは (messageを受けとった回数, beta_dim)
        z = z_memory[t_recieved]
        m = m_memory
        mean, std = self._encoder(z, m)
        KL = -0.5 * torch.mean(torch.sum(1 + torch_log(std**2) - mean**2 - std**2, dim=1))

        # reconstruction loss(再構成誤差)の計算. 
        reconstruction = 0
        beta = None # t=0でメッセージが送られることを前提とした実装になっている
        beta_idx = 0 # beta_memory内の何番目のbetaを呼び出すか
        for t, _ in enumerate(z_memory): 
            if t in self.t_memory: # messageをもらったときのみbetaを更新する
                beta = beta_memory[beta_idx]
                beta_idx += 1
            z_target = z_memory[t:] # (系列長(t~T)) * z_dim
            beta = torch.broadcast_to(beta, (z_target.shape[0], 1, self.beta_dim))
            z_pred = self._decoder(beta)
            z_target = z_target.view(-1, self.z_dim).detach() # (系列長) * z_dim に変換
            reconstruction += F.mse_loss(z_pred, z_target, reduction='sum') /2
            beta = beta[0]
        else: steps = t
        reconstruction /= steps

        return KL, reconstruction 

    def reset_memory(self):
        self.z_memory = []
        self.m_memory = []
        self.beta_memory = []
        self.t_memory = []

"""#### 3-1-3 Controller (C)
潜在変数$z_{t}$と信念状態$\beta$から、行動$a_{t}$を得る。アーキテクチャにはFeed-forward networkを用いる。
"""

# actorとcriticのネットワーク（一部の重みを共有しています）
class Controller(nn.Module):
    def __init__(self, z_dim, beta_dim, num_action, hidden_size=200):
        super(Controller, self).__init__()
        num_state = z_dim + beta_dim
        self.fc1 = nn.Linear(num_state, hidden_size) # 状態を入力
        self.fc2a = nn.Linear(hidden_size, num_action)  # actor独自のlayer
        self.fc2c = nn.Linear(hidden_size, 1)  # critic独自のlayer
    
    def forward(self, z, beta):
        x = torch.cat([z, beta], dim=1)
        h = F.elu(self.fc1(x))
        action_prob = F.softmax(self.fc2a(h), dim=-1)
        state_value = self.fc2c(h)
        # 行動選択確率, 状態価値
        return action_prob, state_value

"""### 3-2 話し手（Speaker）
全体観測$O_{t}$から、全体観測の離散表現であるメッセージ$m_{t}$を出力する。アーキテクチャにはCNN、全結合層を用いる。 また、損失関数には提案手法であるConcept-Clustering (CC)を用いる。  
なお、論文中における記述から、下記を変更した。
- Gumbel softmaxは使用をやめた。
- 全体観測の表現mを1-hotではなく、長さ(m_tokens)の1-hotベクトルを(m_length)個束ねたものに変えた。
"""

def entropy(probs):
    return -torch.sum(probs * torch.log(torch.clamp(probs, min=1e-10)))

class Speaker(nn.Module):
    def __init__(self, m_tokens, m_length, buffer_size=150):
        super(Speaker, self).__init__()
        self.conv_enc1 = nn.Conv2d(3, 8, 3)
        self.conv_enc2 = nn.Conv2d(8, 16, 3)
        self.fc_enc1 = nn.Linear(16*5*5, 500)
        self.fc_enc2 = nn.Linear(500, m_tokens*m_length)

        self.fc_dec1 = nn.Linear(m_tokens*m_length, 500)
        self.fc_dec2 = nn.Linear(500, 500)
        self.fc_dec3 = nn.Linear(500, 3*9*9)

        self.speaker_memory =  torch.empty((buffer_size, 3, 9, 9), dtype=torch.float, device=device) # x_glbを記憶しておくバッファ
        self._memory_index = 0
        self.buffer_size = buffer_size

        self.m_tokens = m_tokens
        self.m_length = m_length

    def _encoder(self, x):
        h = F.relu(self.conv_enc1(x))
        h = F.relu(self.conv_enc2(h))
        h = h.view(-1, 16*5*5)
        h = F.relu(self.fc_enc1(h))
        h = self.fc_enc2(h)
        p = h.view(-1, self.m_length, self.m_tokens)
        return p

    def _decoder(self, m):
        m = m.view(-1, self.m_length*self.m_tokens)
        h = F.relu(self.fc_dec1(m))
        h = F.relu(self.fc_dec2(h))
        h = self.fc_dec3(h)
        h = h.view(-1, 3, 9, 9)
        # 出力が0~1になるようにsigmoid
        x = torch.sigmoid(h)
        return x

    def forward(self, x):
        p = self._encoder(x)
        label = torch.argmax(p, dim=-1)
        message = F.one_hot(label, num_classes=self.m_tokens) - p.detach() + p
        self.speaker_memory[self._memory_index] = torch.squeeze(x).clone() # x_glbを保存
        self._memory_index = (self._memory_index + 1) % self.buffer_size # リングバッファにする
        return message

    def loss(self):
        x = self.speaker_memory
        p = self._encoder(x)
        label = torch.argmax(p, dim=-1)
        m = F.one_hot(label, num_classes=self.m_tokens) - p.detach() + p
        y = self._decoder(m)
        return -entropy(torch.mean(p, dim=0)), torch.mean((x-y)**2)

"""### 3-3 Language World Models
各モジュールを統合し、Language World Modelsを構築する。強化学習アルゴリズムにはREINFORCEを採用する。
"""

class LWMAgent:
    def __init__(self, env, T, 
                 num_state=81, z_dim=8, m_tokens=2, m_length=10, beta_dim=10, 
                 num_action=4, gamma=0.99, message_prob=0.5, 
                 vae_lr=2e-4, lbn_lr=2e-6, ctrl_lr=4e-4, speaker_lr=5e-5, eps=1e-4, 
                 lmd_ent=0.02, lmd_v=0.1):
        super().__init__()
        self.env = env
        self.gamma = gamma  # 割引率
        self.beta_last = None # 最後にメッセージが送られた時のbetaを保存

        self.vae = VAE_Seq(z_dim=z_dim).to(device)
        self.lbn = LBN(T, z_dim=z_dim, m_dim=m_tokens*m_length, beta_dim=beta_dim).to(device)
        self.controller = Controller(z_dim=z_dim, beta_dim=beta_dim, num_action=num_action).to(device)
        self.speaker = Speaker(m_tokens=m_tokens, m_length=m_length).to(device)

        self.vae_memory = [] # xの記憶(VAEの学習のため)
        self.ctrl_memory = []  # （報酬，選択した行動の確率，行動確率, 状態価値, 終了したか）のtupleをlistで保存(Controllerの学習のため)

        self.lmd_ent = lmd_ent # Controllerのlossにおける、エントロピーによる損失の係数
        self.lmd_v = lmd_v # Controllerのlossにおける、価値関数のMSEの係数

        self.message_prob = message_prob # messageが送られる確率

        # オプティマイザの宣言
        self.lwm_optimizer = torch.optim.Adam([
                                              {'params': self.vae.parameters()},
                                              {'params': self.lbn.parameters(), 'lr': lbn_lr}, 
                                              {'params': self.controller.parameters(), 'lr': ctrl_lr},
                                              ], lr=vae_lr, eps=eps)
        self.speaker_optimizer = torch.optim.Adam(self.speaker.parameters(), lr=speaker_lr, eps=eps)

        # スケジューラーの宣言
        #self.speaker_scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(self.speaker_optimizer, 200000, eta_min=1e-6, last_epoch=-1, verbose = False)

    # パラメタを更新
    def update(self):
        # VAEのloss
        vae_memory = torch.squeeze(torch.stack(self.vae_memory))
        vae_kl, vae_reconst = self.vae.loss(vae_memory)
        vae_loss = vae_kl + vae_reconst

        # LBNのloss
        lbn_kl, lbn_reconst = self.lbn.loss()
        lbn_loss = lbn_kl + lbn_reconst

        # Actor-CriticでControllerのlossを計算
        R = 0
        actor_loss = 0
        critic_loss = 0
        entropy_loss = 0
        # エピソード内の各ステップの収益を後ろから計算（方策の良さの指標fをR-vとして, 方策勾配で目的関数を最大化していく）
        for r, prob, action_probs, v in self.ctrl_memory[::-1]:
            R = r + self.gamma * R 
            advantage = R - v # 状態価値関数
            actor_loss -= torch.log(prob) * advantage.detach() # 負の方策勾配(detach()することでactor側の勾配がcritic側に伝わるのを防ぐ)
            critic_loss += F.smooth_l1_loss(v, torch.tensor(R).to(device)) # 状態価値関数のloss(元論文ではMSE)
            entropy_loss += entropy(action_probs) # 探索を活発にするための項、最大化したい
        actor_loss = actor_loss / len(self.ctrl_memory)
        critic_loss = critic_loss / len(self.ctrl_memory)
        entropy_loss = entropy_loss / len(self.ctrl_memory)
        ctrl_loss = actor_loss + self.lmd_v * critic_loss - self.lmd_ent * entropy_loss

        lwm_loss = vae_loss + lbn_loss + ctrl_loss
        self.lwm_optimizer.zero_grad()
        lwm_loss.backward()
        self.lwm_optimizer.step()

        # Speaker
        speaker_negent, speaker_rec = self.speaker.loss()
        speaker_loss = speaker_negent + speaker_rec
        self.speaker_optimizer.zero_grad()
        speaker_loss.backward()
        self.speaker_optimizer.step()
        #self.speaker_scheduler.step()

        return vae_loss, lbn_kl, lbn_reconst, actor_loss, critic_loss, entropy_loss, speaker_negent, speaker_rec
    
    # softmaxの出力が最も大きい行動を選択（テスト時）
    def get_greedy_action(self, t, env):
        '''
        t : 時刻（=ステップ数）
        state : 聞き手の位置（row, column）
        '''
        x_part = env.observation(partial=True).permute(2, 0, 1).reshape(-1, 3, 9, 9).to(device) # 聞き手による部分観測
        x_glb = env.observation(partial=False).permute(2, 0, 1).reshape(-1, 3, 9, 9).to(device) # 話し手による全体観測
        _, z = self.vae(x_part)
        if t == 0 or np.random.rand()<self.message_prob: # t=0の時にはメッセージが送られ、その後は確率message_probでメッセージが送られる
            m = self.speaker(x_glb)
            m = m.view(1,-1)
        else: # メッセージが送られない時
            m = None
        beta = self.lbn(z, m, self.beta_last, t)
        self.beta_last = beta
        action_prob, _ = self.controller(z, self.beta_last)
        action = torch.argmax(action_prob.squeeze().data).item()
        
        return action
    
    # カテゴリカル分布からサンプリングして行動を選択（学習時）
    def get_action(self, t, env): # 本当はenvではなくstate(というよりは観測)を渡してあげるコードの方が分かり易い
        '''
        t : 時刻（=ステップ数）
        state : 聞き手の状態State(row, column)
        '''
        x_part = env.observation(partial=True).permute(2, 0, 1).reshape(-1, 3, 9, 9).to(device) # 聞き手による部分観測
        x_glb = env.observation(partial=False).permute(2, 0, 1).reshape(-1, 3, 9, 9).to(device) # 話し手による全体観測
        self.add_vae_memory(x_part) 
        _, z = self.vae(x_part)
        if t == 0 or np.random.rand()<self.message_prob: # t=0の時にはメッセージが送られ、その後は確率message_probでメッセージが送られる
            m = self.speaker(x_glb)
            m = m.view(1,-1)
        else: # メッセージが送られない時
            m = None
        beta = self.lbn(z, m, self.beta_last, t)
        self.beta_last = beta
        action_prob, state_value = self.controller(z, self.beta_last)
        action_prob, state_value = action_prob.squeeze(), state_value.squeeze()
        action = Categorical(action_prob).sample().item()

        return action, action_prob[action], state_value, action_prob # action_probはControllerのlossにおけるエントロピーの項を計算するのに用いる

    def add_vae_memory(self, x):    
        self.vae_memory.append(x)

    def add_ctrl_memory(self, r, prob, action_prob, v):
        self.ctrl_memory.append((r, prob, action_prob, v))

    def reset_memory(self):
        self.vae_memory = []
        self.ctrl_memory = []
        self.lbn.reset_memory()

'''
"""## 4 学習

- ゴール位置を二種類に減らして実験
- 1,7と-2,7の場合  
  - **betaが少し分離している感**があった
  - 探索step数が大事な可能性
- 探索step回数を変えて実行
  - 1,3 と-2,3
  - 結果は、、、step数30の方はうまくいかず、24の方はうまくいった
    - 深層強化学習の学習の不安定性が関係か。
    - step数としてはどちらも少し余裕を見ている（やろうと思えば22回で二つとも回れてしまう）。
- 他にも位置大事説や、ent増やすといい説を調べたい。
"""

# 各種設定
num_episode = 200000  # 学習エピソード数
T = 36 # エピソードの最大ステップ数
env = Environment(grid_type='A') # 環境
agent = LWMAgent(env, T) # モデルの定義

# ログ
writer = SummaryWriter(log_dir="./logs") # TensorBoardの設定
test_interval = 100
log_interval = 5000
success_rate = 0
test_success_rate = 0
best_success_rate = 0

for episode in tqdm(range(num_episode)):
    env.reset()
    for t in range(T):
        action, prob, state_value, action_prob = agent.get_action(t, env)  #  行動を選択
        next_state, reward, done = env.step(action)
        agent.add_ctrl_memory(reward, prob, action_prob, state_value)
        #　エピソードが終了、エピソードの最大ステップ数に到達したら
        if done or t==T-1:
            if done:
                success_rate += 1
            vae_loss, lbn_kl, lbn_reconst, actor_loss, critic_loss, entropy_loss, speaker_negent, speaker_rec = agent.update()
            agent.reset_memory() # パラメタが更新されているので
            break

    # テスト 探索ノイズなしでの性能を評価する
    if (episode + 1) % test_interval == 0:
        env.reset()
        for t in range(T):
            action = agent.get_greedy_action(t, env)  #  行動を選択
            next_state, reward, done = env.step(action)
            #　エピソードが終了、エピソードの最大ステップ数に到達したら
            if done or t==T-1:
                if done:
                    test_success_rate += 1
                agent.reset_memory()
                break
        
    # 記録する
    writer.add_scalar("t", t, episode+1)
    writer.add_scalar("vae loss", vae_loss.item(), episode+1)
    writer.add_scalar("lbn kl", lbn_kl.item(), episode+1)
    writer.add_scalar("lbn reconst", lbn_reconst.item(), episode+1)
    writer.add_scalar("actor loss", actor_loss.item(), episode+1)
    writer.add_scalar("critic loss", critic_loss.item(), episode+1)
    writer.add_scalar("entropy loss", entropy_loss.item(), episode+1)
    writer.add_scalar("speaker negent", speaker_negent.item(), episode+1)
    writer.add_scalar("speaker rec", speaker_rec.item(), episode+1)

    if (episode+1) % log_interval == 0:
        success_rate /= log_interval
        test_success_rate /= (log_interval / test_interval)

        writer.add_scalar("success rate", success_rate, episode+1)
        writer.add_scalar("test success rate", test_success_rate, episode+1)

        print("Episode %d finished | Success rate %f" % (episode+1, success_rate))
        print("Episode %d finished | Test success rate %f" % (episode+1, test_success_rate))

        # 重みの保存
        if best_success_rate < test_success_rate:
            torch.save(agent.vae.state_dict(), './vae_best.pth')
            torch.save(agent.lbn.state_dict(), './lbn_best.pth')
            torch.save(agent.controller.state_dict(), './controller_best.pth')
            torch.save(agent.speaker.state_dict(), './speaker_best.pth')
            best_success_rate = test_success_rate
        else:
            torch.save(agent.vae.state_dict(), './vae_last.pth')
            torch.save(agent.lbn.state_dict(), './lbn_last.pth')
            torch.save(agent.controller.state_dict(), './controller_last.pth')
            torch.save(agent.speaker.state_dict(), './speaker_last.pth')
            best_success_rate = test_success_rate              

        success_rate = 0
        test_success_rate = 0

# writerを閉じる
writer.close()

'''

'''

"""## 5 挙動確認

### 5-1 VAE-Seq
"""
def vae_exp(self):
    with torch.no_grad():
        self.env.reset()
        x_part = self.env.observation(partial=True)
        print('input')
        plt.imshow(x_part)
        plt.show()
        x_part = x_part.permute(2, 0, 1).reshape(-1, 3, 9, 9).to(device) 
        _, z = self.agent.vae(x_part)
        x_img = self.agent.vae._decoder(z).reshape(3, 9, 9).permute(1, 2, 0).cpu().detach().numpy()
        print('output')
        plt.imshow(x_img)
        plt.show()
        self.agent.reset_memory()


"""### 5-2 Speaker"""
def speaker_exp(self):
    with torch.no_grad():
        fig, ax = plt.subplots(2,6,figsize=(15,5))
        for i in range(6):
            self.env.reset()
            x_glb = self.env.observation(partial=False)
            ax[0][i].imshow(x_glb)
            x_glb = x_glb.permute(2, 0, 1).reshape(-1, 3, 9, 9).to(device) 
            m = self.agent.speaker(x_glb)
            x_re = self.agent.speaker._decoder(m)
            x_re = x_re.reshape(3, 9, 9).permute(1, 2, 0).cpu().detach().numpy()
            ax[1][i].imshow(x_re)
            self.agent.reset_memory()
        plt.show()
        self.agent.reset_memory()
'''


"""## 6 重みの読み込み"""

# モデルの定義
T = 30
env = Environment(grid_type='A')
agent = LWMAgent(env, T, device)

# 保存したモデルパラメータの読み込み
agent.vae.load_state_dict(torch.load('./vae_best.pth'))
agent.lbn.load_state_dict(torch.load('./lbn_best.pth'))
agent.controller.load_state_dict(torch.load('./controller_best.pth'))
agent.speaker.load_state_dict(torch.load('./speaker_best.pth'))


with torch.no_grad():
    fig, ax = plt.subplots(1,6,figsize=(12,3))

    slot_lst = []
    beta_lst = []

    for i in range(2):
        env.reset()
        x_part = env.observation(partial=True)
        x_glb = env.observation(partial=False)
        ax[i].imshow(x_glb)

        x_glb = x_glb.permute(2, 0, 1).reshape(-1, 3, 9, 9).to(device) 
        m = agent.speaker(x_glb)
        m = m.view(1,20)

        x_part = x_part.permute(2, 0, 1).reshape(-1, 3, 9, 9).to(device)
        _, z_init = agent.vae(x_part)

        for _ in range(1000):
            beta = agent.lbn(z_init, m, beta=None, t=1).view(-1).detach().cpu().tolist()
            beta_lst.append(beta)
            slot_lst.append(i)
    
    plt.savefig('lbn_input.jpg')
        
    from sklearn.manifold import TSNE
    beta_lst = TSNE(n_components=2).fit_transform(beta_lst).T

    colors = ['red', 'blue','green','magenta','cyan','yellow']
    plt.figure(figsize=(8,8))
    plt.scatter(beta_lst[0], beta_lst[1], s=0.7, c=[colors[t] for t in slot_lst])
    plt.savefig('lbn_output.jpg')


