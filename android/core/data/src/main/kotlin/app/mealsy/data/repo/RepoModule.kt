package app.mealsy.data.repo

import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

@Module
@InstallIn(SingletonComponent::class)
abstract class RepoModule {

    @Binds
    abstract fun bindConversationIdStore(impl: DataStoreConversationIdStore): ConversationIdStore

    @Binds
    abstract fun bindProfileStore(impl: DataStoreProfileStore): ProfileStore
}
