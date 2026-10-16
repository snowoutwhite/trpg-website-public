/**
 * 玩家卡 / GM 卡与个人空间（apps/profiles）。
 * 字段核对自 apps/profiles/serializers.py 与 urls.py。
 *
 * 隐私：公开视角下 likes / dislikes 在档位未公布时为 null（后端故意不外露绝对值，
 * 否则能手算比例绕过公布阈值）。前端不得试图从别处拼出这个数。
 */
import { request } from './http'
import type { PublicUser } from './site'

export interface PlayerCard {
  taboos: string
  preferred_rule_systems: string[]
  free_text: string
  games_played: number
  /** 未达公布阈值（或站主关掉赞功能）时后端回 null，见 `_MaskedCountsMixin`。 */
  reviews_received: number | null
  likes: number | null
  dislikes: number | null
  /** 档位代码；空串表示被评数未达公布阈值。 */
  level: string
  level_display: string
}

export interface GMCard {
  style_text: string
  games_hosted: number
  /** 未达公布阈值（或站主关掉赞功能）时后端回 null，见 `_MaskedCountsMixin`。 */
  reviews_received: number | null
  likes: number | null
  dislikes: number | null
  level: string
  level_display: string
}

export interface PublicProfile {
  user: PublicUser
  player_card: PlayerCard
  /** 非 GM 时为 null。 */
  gm_card: GMCard | null
}

const BASE = '/api/v1/profiles'

export function fetchPublicProfile(userId: number | string): Promise<PublicProfile> {
  return request<PublicProfile>(BASE + '/users/' + userId + '/', { skipAuthRedirect: true })
}

export function fetchMyPlayerCard(): Promise<PlayerCard> {
  return request<PlayerCard>(BASE + '/me/player-card/')
}

export function updateMyPlayerCard(
  payload: Partial<Pick<PlayerCard, 'taboos' | 'preferred_rule_systems' | 'free_text'>>,
): Promise<PlayerCard> {
  return request<PlayerCard>(BASE + '/me/player-card/', { method: 'PATCH', body: payload })
}

export function fetchMyGMCard(): Promise<GMCard> {
  return request<GMCard>(BASE + '/me/gm-card/')
}

export function updateMyGMCard(payload: Partial<Pick<GMCard, 'style_text'>>): Promise<GMCard> {
  return request<GMCard>(BASE + '/me/gm-card/', { method: 'PATCH', body: payload })
}
