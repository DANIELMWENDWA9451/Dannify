<template>
  <div class="pb-12">
    <div v-if="loading && !artist" class="view-pad pt-10">
      <div class="flex items-end gap-6">
        <div class="skeleton h-48 w-48 rounded-full" />
        <div class="flex-1 space-y-3">
          <div class="skeleton h-4 w-24" />
          <div class="skeleton h-12 w-1/2" />
        </div>
      </div>
    </div>

    <EmptyState
      v-else-if="!artist"
      icon="ph:user"
      :title="t('artist.notFound')"
    >
      <button class="btn btn-pill" @click="router.push({ name: 'Artists' })">{{ t('artist.back') }}</button>
    </EmptyState>

    <template v-else>
      <CollectionHero
        :title="artist.name"
        :label="t('artist.label')"
        :cover="coverUrl"
        kind="artist"
        round
        :playing="playingHere"
        @play="playAll"
      >
        <template #meta>
          <span>{{ t('artists.trackCount', { count: artist.count }) }}</span>
          <span class="opacity-50">•</span>
          <span>{{ t('artist.albumCount', { count: artist.albums.length }) }}</span>
        </template>
        <template #actions>
          <button class="play-fab" :title="t('artists.playAll')" @click="playAll">
            <Icon :icon="playingHere ? 'ph:pause-fill' : 'ph:play-fill'" class="h-5 w-5" />
          </button>
          <button class="icon-btn is-round h-10 w-10" :title="t('artist.shuffle')" @click="shuffleRows(allRows)">
            <Icon icon="ph:shuffle" class="h-6 w-6" />
          </button>
          <button class="btn btn-pill" :disabled="onlineLoading || onlineLoaded" @click="loadOnline">
            <Icon :icon="onlineLoading ? 'ph:spinner-gap' : onlineLoaded ? 'ph:check' : 'ph:globe'" class="h-4 w-4" :class="{ 'animate-spin': onlineLoading }" />
            {{ onlineLoading ? t('artist.loadingOnline') : onlineLoaded ? t('artist.onlineLoaded') : t('artist.loadOnline') }}
          </button>
        </template>
      </CollectionHero>

      <!-- One list, with the album on the row. It used to be a heading per
           album, which meant a library that is mostly singles turned into a
           column of headings with one track under each. The online artist
           page has always been a plain list; this is the same thing. -->
      <section class="view-pad mb-8">
        <TrackTable
          :rows="allRows"
          :sticky-offset="56"
          show-album
          deletable
          :on-play="(i) => playRows(allRows, i)"
        />
      </section>

      <section v-if="onlineLoaded || onlineLoading || onlineError" class="view-pad mb-8">
        <div class="mb-3 flex items-center justify-between gap-3">
          <h2 class="text-lg font-bold">{{ t('artist.onlineCatalog') }}</h2>
          <button v-if="onlineError" class="btn-ghost h-8 text-xs" @click="onlineLoaded = false; loadOnline()">
            {{ t('common.retry') }}
          </button>
        </div>
        <div v-if="onlineLoading" class="py-8 text-center text-sm text-fg/55">
          {{ t('artist.loadingOnline') }}
        </div>
        <EmptyState
          v-else-if="onlineError"
          compact
          icon="ph:warning-circle"
          :title="t('artist.onlineFailed')"
        />
        <EmptyState
          v-else-if="!onlineRows.length"
          compact
          icon="ph:music-notes"
          :title="t('artist.onlineEmpty')"
        />
        <TrackTable
          v-else
          :rows="onlineRows"
          :sticky-offset="56"
          :on-play="(i) => playRows(onlineRows, i)"
        />
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import API from '/src/model/api'
import { usePlayer } from '/src/model/player'
import { localRow, songRow, playRows, shuffleRows } from '/src/model/tracks'
import { onRefresh, onLibraryChanged } from '/src/model/useRefresh'
import { useI18n } from '/src/i18n'
import CollectionHero from '/src/components/ui/CollectionHero.vue'
import TrackTable from '/src/components/ui/TrackTable.vue'
import EmptyState from '/src/components/ui/EmptyState.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const player = usePlayer()

const artist = ref(null)
const loading = ref(false)
const onlineRows = ref([])
const onlineLoading = ref(false)
const onlineLoaded = ref(false)
const onlineError = ref(false)

const coverUrl = computed(() =>
  artist.value && artist.value.cover ? API.coverFileURL(artist.value.cover, artist.value.cover_v) : ''
)

const albums = computed(() =>
  artist.value
    ? artist.value.albums.map((al) => ({ ...al, rows: al.tracks.map(localRow) }))
    : []
)
const allRows = computed(() => albums.value.flatMap((al) => al.rows))

// Whether what is playing belongs to this page, and separately whether it is
// actually running. Both used to be one flag, so a paused collection looked
// unplayed and the same button that paused it started it again from the top.
const currentHere = computed(() => {
  const cur = player.currentTrack.value
  return !!cur && allRows.value.some((r) => r.file && r.file === cur.file)
})
const playingHere = computed(() => currentHere.value && player.isPlaying.value)

function playAll() {
  if (currentHere.value) return player.toggle()
  player.setShuffle(false)
  playRows(allRows.value, 0)
}

async function loadOnline() {
  if (!artist.value || onlineLoading.value || onlineLoaded.value) return
  onlineLoading.value = true
  onlineError.value = false
  try {
    const res = await API.exploreSearch(artist.value.name, 50)
    const name = artist.value.name.toLowerCase()
    const songs = Array.isArray(res.data?.songs) ? res.data.songs : []
    onlineRows.value = songs
      .filter((song) => {
        const names = Array.isArray(song.artist_ids)
          ? song.artist_ids.map((value) => (typeof value === 'object' ? value.name : value))
          : Array.isArray(song.artists)
            ? song.artists
            : [song.artist]
        return names.some((value) => String(value || '').toLowerCase() === name)
      })
      .map(songRow)
    onlineLoaded.value = true
  } catch {
    onlineError.value = true
  } finally {
    onlineLoading.value = false
  }
}

async function load(resetOnline = true) {
  const name = route.params.name
  if (!name) return
  loading.value = true
  if (resetOnline) {
    onlineRows.value = []
    onlineLoaded.value = false
    onlineError.value = false
  }
  try {
    const res = await API.getArtist(name)
    artist.value = res.data
  } catch {
    artist.value = null
  } finally {
    loading.value = false
  }
}

onMounted(() => load())
watch(() => route.params.name, () => load())
onRefresh(() => load(false))
onLibraryChanged(() => setTimeout(() => load(false), 800))
</script>
